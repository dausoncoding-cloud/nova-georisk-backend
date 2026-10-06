"""Sourced map methods: externally reviewed choices, never invented scientific defaults."""
import re
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.strict import StrictModel
from app.services.ml.contracts import ClassifierType


class LegendBand(StrictModel):
    label: str = Field(min_length=1,max_length=128)
    color: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    min: float = Field(ge=0,le=1)
    max: float = Field(ge=0,le=1)


class SusceptibilityMethod(StrictModel):
    method_reference: str = Field(min_length=3,max_length=512)
    method_version: str = Field(min_length=1,max_length=64)
    historical_observation_reference: str = Field(min_length=3,max_length=512)
    label_definition: str = Field(min_length=10,max_length=1000)
    class_labels: dict[str,str]
    response: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
    predictor_order: list[str] = Field(min_length=1,max_length=64)
    algorithm: ClassifierType
    n_estimators: int = Field(ge=10,le=2000)
    train_fraction: float = Field(ge=.5,lt=1)
    random_seed: int
    split_policy: Literal['chronological']
    display_legend: list[LegendBand] = Field(min_length=2,max_length=16)

    @model_validator(mode='after')
    def explicit_method(self):
        if set(self.class_labels)!={'0','1'} or any(not value.strip() for value in self.class_labels.values()) or len(set(self.class_labels.values()))!=2:
            raise ValueError('Susceptibility requires two sourced, distinct historical class meanings')
        if len(set(self.predictor_order))!=len(self.predictor_order) or self.response in self.predictor_order:
            raise ValueError('Predictor catalogue order must be unique and exclude response')
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name) for name in self.predictor_order):
            raise ValueError('Predictor names must be canonical catalogue keys')
        bands=self.display_legend
        if len({band.label for band in bands})!=len(bands):
            raise ValueError('Reviewed display class labels must be distinct')
        if bands[0].min!=0 or bands[-1].max!=1 or any(b.min>=b.max for b in bands) or any(a.max!=b.min for a,b in zip(bands,bands[1:])):
            raise ValueError('Reviewed display bands must partition [0,1] without gaps or overlap')
        return self


class ReviewedMapOptions(StrictModel):
    method_reference: str = Field(min_length=3,max_length=512)


class ZoneClass(StrictModel):
    label: str = Field(min_length=1,max_length=128)
    color: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')


FACTOR_UNITS={'depth':'m','velocity':'m/s','duration':'hours','aep':'annual_probability_0_1','exposure':'index_0_1'}


class ZonationDefinition(StrictModel):
    method: Literal['reviewed_interval_decision_table']
    method_reference: str = Field(min_length=3,max_length=512)
    method_version: str = Field(min_length=1,max_length=64)
    definition: str = Field(min_length=10,max_length=1000)
    factor_units: dict[str,str]
    classes: dict[str,ZoneClass]

    @model_validator(mode='after')
    def sourced_factors(self):
        if not {'depth','velocity'}.issubset(self.factor_units) or not 3<=len(self.factor_units)<=5 or any(FACTOR_UNITS.get(k)!=v for k,v in self.factor_units.items()):
            raise ValueError('Multi-factor zonation requires depth, velocity and at least one supported sourced factor with canonical units')
        if not 2<=len(self.classes)<=16 or set(self.classes)!={str(i) for i in range(1,len(self.classes)+1)}:
            raise ValueError('Sourced zone definitions require consecutive codes 1..N, with 2–16 classes')
        if len({value.label for value in self.classes.values()})!=len(self.classes):
            raise ValueError('Sourced zone labels must be distinct')
        return self
