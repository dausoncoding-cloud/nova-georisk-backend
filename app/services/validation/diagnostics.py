"""Persistable diagnostics and standard ReportLab plots of supplied observations."""
from dataclasses import asdict
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.graphics import renderSVG
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from sklearn.metrics import roc_curve, precision_recall_curve, average_precision_score

from app.platform.result_exports import artifact_entry
from app.services.reporting.complete_report import _spreadsheet_safe
from app.services.source_data.bundle4 import clean
from app.services.validation.regression_metrics import compute_regression_metrics
from app.services.validation.classification_metrics import compute_classification_metrics, classification_metrics_from_counts, ConfusionCounts

LIMITATIONS = ['Metrics describe supplied paired observations only; no independent certification, calibration or forecast skill is inferred.',
               'Threshold sweeps are descriptive operating points; no safety threshold or optimal policy is selected.']


def paired(observed, predicted):
    observed, predicted = np.asarray(observed, dtype=float), np.asarray(predicted, dtype=float)
    if observed.ndim != 1 or observed.shape != predicted.shape or not len(observed) or len(observed) > 25000:
        raise ValueError('Diagnostics require 1–25,000 matching one-dimensional observed/predicted pairs')
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all() or not np.isfinite(observed-predicted).all():
        raise ValueError('Nonfinite observations or derived errors cannot be validated')
    return observed, predicted


def continuous_diagnostics(observed, predicted):
    observed, predicted = paired(observed, predicted)
    metrics = asdict(compute_regression_metrics(observed, predicted))
    if any(np.isinf(value) for value in metrics.values()):
        raise ValueError('Regression diagnostics overflow the supported numeric contract')
    return {'metrics': clean(metrics), 'availability': {'percentage_errors': {'available': bool(np.count_nonzero(observed)),
            'reason': 'Undefined at zero observations; denominators exclude those pairs', 'denominator': int(np.count_nonzero(observed))},
            'undefined_metrics': {'available': False, 'reason': 'Zero denominator/variance under the existing formula',
                                  'keys': [key for key, value in metrics.items() if isinstance(value, float) and np.isnan(value)]}}, 'curves': {}}


def binary_diagnostics(observed, predicted, scores=None):
    observed, predicted = paired(observed, predicted)
    if not np.isin(observed, [0, 1]).all() or not np.isin(predicted, [0, 1]).all():
        raise ValueError('Current classifier diagnostics are explicitly binary; multiclass requires a supported model')
    both = len(np.unique(observed)) == 2
    if scores is not None:
        scores = np.asarray(scores, dtype=float)
        if scores.shape != observed.shape or not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
            raise ValueError('Conditional model scores must be finite matching values in [0,1]; they are not flood AEP')
    metrics = asdict(compute_classification_metrics(observed, predicted, y_score=scores if scores is not None and both else None))
    metrics['class_support'] = {str(code): int(np.count_nonzero(observed == code)) for code in (0, 1)}
    metrics['predicted_class_support'] = {str(code): int(np.count_nonzero(predicted == code)) for code in (0, 1)}
    # Each class uses the existing formulas; weighted and macro summaries preserve undefined values.
    per_class = {str(code): asdict(compute_classification_metrics(observed, predicted, positive_label=code)) for code in (0, 1)}
    metrics['per_class'] = per_class
    for name in ('precision', 'recall', 'f1_score'):
        values = np.array([per_class[str(code)][name] for code in (0, 1)])
        metrics['macro_'+name] = float(values.mean()) if np.isfinite(values).all() else None
        support = np.array([metrics['class_support'][str(code)] for code in (0, 1)])
        included = support > 0
        metrics['weighted_'+name] = float(np.sum(values[included]*support[included])/support.sum()) if np.isfinite(values[included]).all() else None
    curves = {}
    if scores is not None and both:
        fpr, tpr, thresholds = roc_curve(observed, scores, drop_intermediate=False)
        precision, recall, pr_thresholds = precision_recall_curve(observed, scores)
        curves['roc'] = [{'false_positive_rate': f, 'true_positive_rate': t, 'threshold': q if np.isfinite(q) else None,
                          'boundary': 'finite_score_threshold' if np.isfinite(q) else 'no_predicted_positives'} for f, t, q in zip(fpr, tpr, thresholds)]
        curves['precision_recall'] = [{'recall': r, 'precision': p, 'threshold': pr_thresholds[i] if i < len(pr_thresholds) else None,
                                      'boundary': 'finite_score_threshold' if i < len(pr_thresholds) else 'no_predicted_positives'} for i, (r, p) in enumerate(zip(recall, precision))]
        curves['thresholds'] = []
        order = np.argsort(scores, kind='stable')
        sorted_scores, sorted_labels = scores[order], observed[order].astype(int)
        positive_prefix = np.concatenate(([0], np.cumsum(sorted_labels)))
        n_pos, n_neg = int(np.sum(observed)), int(len(observed)-np.sum(observed))
        for cutoff in np.unique(scores):
            before = int(np.searchsorted(sorted_scores, cutoff, side='left'))
            fn, tn = int(positive_prefix[before]), int(before-positive_prefix[before])
            record = asdict(classification_metrics_from_counts(ConfusionCounts(n_pos-fn, tn, n_neg-tn, fn)))
            curves['thresholds'].append({'threshold': cutoff, 'rule': 'score >= threshold', **record})
        metrics['average_precision'] = float(average_precision_score(observed, scores))
    if scores is not None:
        metrics['brier_score'] = float(np.mean((scores-observed)**2))
    reason = 'Both observed classes and supplied conditional scores are required'
    return clean({'metrics': metrics, 'curves': curves, 'availability': {
        'roc_precision_recall_threshold_sweep': {'available': bool(curves), 'reason': None if curves else reason},
        'multiclass': {'available': False, 'reason': 'Current FIRRIS classifiers are binary; no multiclass labels inferred'},
        'independent_calibration': {'available': False, 'reason': 'Requires independently reviewed observations and calibration evidence'}}})


def line_plot(title, series, *, scatter=False, x_label='x', y_label='y'):
    drawing = Drawing(460, 280)
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 65, 45, 365, 190
    plot.data = [list(zip(np.asarray(x, float).tolist(), np.asarray(y, float).tolist())) for x, y in series]
    plot.joinedLines = not scatter
    for i in range(len(series)):
        plot.lines[i].strokeColor = colors.HexColor(('#176BA0', '#B94B28', '#47813B')[i % 3])
        if scatter: plot.lines[i].symbol = makeMarker('FilledCircle', size=3)
    drawing.add(plot)
    drawing.add(String(65, 255, title[:75], fontSize=12))
    drawing.add(String(100, 12, x_label[:60], fontSize=9))
    drawing.add(String(2, 245, y_label[:60], fontSize=8))
    return drawing


def bar_plot(title, labels, values):
    drawing = Drawing(460, 280)
    plot = VerticalBarChart()
    plot.x, plot.y, plot.width, plot.height = 65, 65, 365, 170
    plot.data = [list(map(float, values))]
    plot.categoryAxis.categoryNames = list(map(str, labels))
    plot.categoryAxis.labels.angle = 30
    drawing.add(plot)
    drawing.add(String(65, 255, title[:75], fontSize=12))
    return drawing


def write_diagnostic_artifacts(directory, observed, predicted, *, kind, units, scope, version, scores=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    observed, predicted = paired(observed, predicted)
    result = continuous_diagnostics(observed, predicted) if kind == 'continuous' else binary_diagnostics(observed, predicted, scores)
    drawings = {}
    if kind == 'continuous':
        residuals = observed-predicted
        drawings['observed_predicted'] = line_plot('Observed versus predicted (supplied pairs)', [(observed, predicted)], scatter=True, x_label='Observed '+units, y_label='Predicted '+units)
        drawings['residual_predicted'] = line_plot('Residual = observed - predicted', [(predicted, residuals)], scatter=True, x_label='Predicted '+units, y_label='Residual '+units)
        drawings['paired_values'] = line_plot('Paired observations in supplied order', [(np.arange(len(observed)), observed), (np.arange(len(observed)), predicted)], x_label='Pair index (not a fabricated time series)', y_label=units)
        counts, edges = np.histogram(residuals, bins='sturges')
        drawings['residual_distribution'] = bar_plot('Residual histogram; Sturges display bins only', [f'{a:.3g}..{b:.3g}' for a, b in zip(edges, edges[1:])], counts)
        drawings['absolute_error_predicted'] = line_plot('Absolute error versus predicted', [(predicted, np.abs(residuals))], scatter=True, x_label='Predicted '+units, y_label='Absolute error '+units)
        nonzero = observed != 0
        if nonzero.any():
            drawings['relative_error'] = line_plot('Signed relative residual; zero observations excluded', [(observed[nonzero], residuals[nonzero]/observed[nonzero]*100)], scatter=True, x_label='Observed '+units, y_label='Relative residual (%)')
    else:
        c = result['metrics']['confusion']
        drawings['confusion_counts'] = bar_plot('Binary confusion counts (supplied labels)', ['TP', 'TN', 'FP', 'FN'], [c[key] for key in ('tp', 'tn', 'fp', 'fn')])
        drawings['class_imbalance'] = bar_plot('Observed class support (codes 0 and 1)', ['0', '1'], [result['metrics']['class_support'][key] for key in ('0', '1')])
        if result['curves']:
            roc, pr, sweep = (result['curves'][key] for key in ('roc', 'precision_recall', 'thresholds'))
            drawings['roc'] = line_plot('ROC; supplied conditional scores', [( [p['false_positive_rate'] for p in roc], [p['true_positive_rate'] for p in roc])], x_label='False positive rate', y_label='True positive rate')
            drawings['precision_recall'] = line_plot('Precision–recall; supplied conditional scores', [([p['recall'] for p in pr], [p['precision'] for p in pr])], x_label='Recall', y_label='Precision')
            valid = [p for p in sweep if p['f1_score'] is not None]
            if valid: drawings['threshold_f1'] = line_plot('Diagnostic thresholds; no policy selected', [([p['threshold'] for p in valid], [p['f1_score'] for p in valid])], x_label='Supplied score threshold', y_label='F1')
    entries = {}
    for key, drawing in drawings.items():
        path = directory / ('validation-'+key+'.svg')
        renderSVG.drawToFile(drawing, str(path))
        entries['validation_'+key+'_plot'] = artifact_entry(path, label=key.replace('_', ' '), media_type='image/svg+xml', artifact_type='report', role='export', format_name='svg', result_version=version)
    for key, rows in result['curves'].items():
        # Flatten confusion counts, keeping scalar undefined values as null.
        flat = [{**{k:v for k,v in row.items() if not isinstance(v, dict)}, **row.get('confusion', {})} for row in rows]
        path = directory / ('validation-'+key+'.csv')
        _spreadsheet_safe(pd.DataFrame(flat)).to_csv(path, index=False)
        entries['validation_'+key+'_data'] = artifact_entry(path, label=key+' data', media_type='text/csv', artifact_type='report', role='export', format_name='csv', result_version=version)
    styles = getSampleStyleSheet()
    story = [Paragraph('FIRRIS supplied-observation diagnostics', styles['Heading1']), Paragraph(escape(scope), styles['BodyText'])]
    for text in LIMITATIONS: story.append(Paragraph(escape(text), styles['BodyText']))
    for name, value in result['metrics'].items():
        if not isinstance(value, dict): story.append(Paragraph(escape(f'{name}: {value if value is not None else "undefined"}'), styles['BodyText']))
    for drawing in drawings.values(): story.extend([Spacer(1, 12), drawing])
    pdf = directory/'validation-report.pdf'
    SimpleDocTemplate(str(pdf)).build(story)
    entries['validation_report'] = artifact_entry(pdf, label='Validation metrics and plots', media_type='application/pdf', artifact_type='report', role='export', format_name='pdf', result_version=version)
    dashboard = {'kind': kind, 'metrics': result['metrics'], 'availability': result['availability'], 'plots': [key for key in entries if key.endswith('_plot')],
                 'scope': scope, 'units': units, 'limitations': LIMITATIONS}
    return dashboard, entries
