"""Synthetic protocol fixtures; these are not scientific validation inputs."""
import json
import zipfile
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.services.gee.band_export import assemble_export, request_contract, digest, EXPORT_FORMAT
from app.services.gee import firris_pipeline

BANDS = ['B3', 'B8', 'B11']


def contract(bands=None):
    return request_contract('synthetic serialized image', 'synthetic region', bands or BANDS, scale=30, crs='EPSG:4326')


def raster(value, *, description=None, count=1, shifted=False, dtype='float32', mask=False, no_crs=False, validity=False):
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=2, height=2, count=count, dtype=dtype,
                         crs=None if no_crs else 'EPSG:4326', transform=from_origin(1 if shifted else 0, 2, 1, 1), nodata=-9999) as out:
            values = np.full((count, 2, 2), value, dtype=dtype)
            if mask: values[:, 0, 0] = -9999
            if validity: values[:,0,0] = 0
            out.write(values)
            if description: out.set_band_description(1, description)
        return memory.read()


def archive(tmp_path, request=None, fault=None):
    request = request or contract()
    path = tmp_path / 'synthetic.download'
    names = request['bands'] + request['validity_bands']
    with zipfile.ZipFile(path, 'w') as output:
        # Deliberately shuffled ZIP members: IDs, never physical order, govern.
        for index in reversed(range(len(names))):
            band = names[index]
            if fault == 'missing' and index == 0: continue
            name = request['filename_prefix'] + '.' + band + '.tif'
            if fault == 'unknown' and index == 0: name = request['filename_prefix']+'.unknown.tif'
            if fault == 'anonymous' and index == 0: name = 'download.tif'
            if fault == 'wrong_request' and index == 0: name = 'another_request.'+band+'.tif'
            if fault == 'traversal' and index == 0: name = '../'+name
            output.writestr(name, raster(1 if band.startswith('valid__') else index+1, description='B11' if fault == 'conflict' and index == 0 else None,
                                        count=2 if fault == 'count' and index == 0 else 1,
                                        shifted=fault == 'grid' and index == 0,
                                        no_crs=fault == 'crs' and index == 0,
                                        mask=not band.startswith('valid__'), validity=band.startswith('valid__')))
            if fault == 'duplicate' and index == 0:
                with pytest.warns(UserWarning): output.writestr(name, raster(88))
        if fault == 'extra': output.writestr('unexpected.txt', 'synthetic')
    return path


def test_provider_filenames_preserve_names_order_samples_masks_and_audit(tmp_path):
    request = contract()
    downloaded = archive(tmp_path, request)
    before = downloaded.read_bytes()
    output, sidecar, manifest = assemble_export(downloaded, request)
    with rasterio.open(output) as source:
        assert list(source.descriptions) == BANDS
        assert source.count == 3
        assert source.crs.to_string() == 'EPSG:4326'
        assert source.tags()['gee_export_request_sha256'] == request['request_sha256']
        for index in range(3):
            values = source.read(index+1, masked=True)
            assert values.mask[0, 0]
            assert values[1, 1] == index+1
    assert downloaded.read_bytes() == before
    assert json.loads(sidecar.read_text()) == manifest
    assert manifest['request']['bands'] == BANDS
    assert [item['band'] for item in manifest['ordered_bands']] == BANDS
    assert all(item['provider_description'] is None for item in manifest['ordered_bands'])
    assert manifest['provider_archive']['sha256'] == digest(downloaded)
    assert manifest['canonical_raster']['sha256'] == digest(output)
    assert all(digest(tmp_path/'gee-extracted'/item['member']) == item['sha256'] for item in manifest['ordered_bands'])


@pytest.mark.parametrize('fault', ['missing','unknown','anonymous','wrong_request','traversal','duplicate','extra','conflict','count','grid','crs'])
def test_invalid_provider_identity_or_grid_rejected(tmp_path, fault):
    with pytest.raises(ValueError): assemble_export(archive(tmp_path, fault=fault), contract())
    assert not (tmp_path/'synthetic.bands.json').exists()
    assert not (tmp_path/'synthetic.tif').exists()


@pytest.mark.parametrize('named', [True, False])
def test_multiband_tiff_without_per_band_delivery_metadata_rejected(tmp_path, named):
    path = tmp_path/'anonymous.tif'
    path.write_bytes(raster(1, description='B3' if named else None, count=3))
    with pytest.raises(ValueError, match='identity metadata'): assemble_export(path, contract())


@pytest.mark.parametrize('bands', [['B3','B3'], ['B3','../B8'], ['B3',None]])
def test_invalid_expected_band_contract_rejected(bands):
    with pytest.raises(ValueError): contract(bands)


def test_request_identity_binds_band_order_image_region_scale_and_crs():
    baseline = contract()
    variants = [contract(list(reversed(BANDS))),
                request_contract('different image', 'synthetic region', BANDS, scale=30, crs='EPSG:4326'),
                request_contract('synthetic serialized image', 'different region', BANDS, scale=30, crs='EPSG:4326'),
                request_contract('synthetic serialized image', 'synthetic region', BANDS, scale=10, crs='EPSG:4326'),
                request_contract('synthetic serialized image', 'synthetic region', BANDS, scale=30, crs='EPSG:3857')]
    assert all(item['request_sha256'] != baseline['request_sha256'] for item in variants)
    assert contract() == baseline


def test_export_explicitly_requests_ordered_band_ids_and_per_band_format(monkeypatch, tmp_path):
    request = contract()
    image = MagicMock()
    response = MagicMock()
    response.headers = {'content-length':'9'}
    response.iter_content.return_value = [b'synthetic']
    monkeypatch.setattr(firris_pipeline.requests, 'get', lambda *args, **kw: response)
    firris_pipeline._download_image(image, {}, tmp_path/'download', scale=30, crs='EPSG:4326', contract=request)
    params = image.getDownloadURL.call_args.args[0]
    assert params['format'] == EXPORT_FORMAT
    assert params['filePerBand'] is True
    assert params['bands'] == BANDS+request['validity_bands']
    assert params['name'] == request['filename_prefix']
    response.close.assert_called_once()


def test_band_order_must_match_remote_materialization_before_download(monkeypatch, tmp_path):
    # Existing full acquisition fixture independently exercises the remote gate;
    # this check covers order-bound provider names from a different request.
    wrong = contract(list(reversed(BANDS)))
    with pytest.raises(ValueError): assemble_export(archive(tmp_path, wrong), contract())


def test_expanded_archive_capacity_is_bounded(monkeypatch, tmp_path):
    from app.services.gee import band_export
    path = archive(tmp_path)
    monkeypatch.setattr(band_export, 'MAX_EXPORT_BYTES', 10)
    with pytest.raises(ValueError, match='capacity'): assemble_export(path, contract())


def test_explicit_validity_preserves_valid_zero_and_excludes_missing_samples(tmp_path):
    request = contract(['label'])
    path = tmp_path/'synthetic.download'
    with zipfile.ZipFile(path, 'w') as output:
        for band, is_validity in [('label',False),('valid__label',True)]:
            with MemoryFile() as memory:
                with memory.open(driver='GTiff',width=2,height=2,count=1,dtype='uint8',
                                 crs='EPSG:4326',transform=from_origin(0,2,1,1),nodata=0) as raster_out:
                    raster_out.write(np.array([[0,1],[1,1]] if is_validity else [[0,0],[1,0]],dtype='uint8'),1)
                output.writestr(request['filename_prefix']+'.'+band+'.tif',memory.read())
    output,_,_ = assemble_export(path,request)
    with rasterio.open(output) as source:
        values=source.read(1,masked=True)
        assert values.mask.tolist()==[[True,False],[False,False]]
        assert values[0,1]==0 and values[1,1]==0 and values[1,0]==1


@pytest.mark.parametrize('missing', [True,False])
def test_missing_or_nonbinary_validity_evidence_fails_closed(tmp_path,missing):
    request=contract(['label'])
    path=tmp_path/'synthetic.download'
    with zipfile.ZipFile(path,'w') as output:
        output.writestr(request['filename_prefix']+'.label.tif',raster(1))
        if not missing: output.writestr(request['filename_prefix']+'.valid__label.tif',raster(0.5))
    with pytest.raises(ValueError): assemble_export(path,request)
