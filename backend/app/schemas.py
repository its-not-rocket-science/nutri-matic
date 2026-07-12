from pydantic import BaseModel, ConfigDict, Field


class AminoAcidProfile(BaseModel):
    histidine: float | None = None
    isoleucine: float | None = None
    leucine: float | None = None
    lysine: float | None = None
    met_cys: float | None = Field(default=None, description="methionine + cysteine")
    phe_tyr: float | None = Field(default=None, description="phenylalanine + tyrosine")
    threonine: float | None = None
    tryptophan: float | None = None
    valine: float | None = None


class FoodCreate(BaseModel):
    name: str
    protein_g_per_100g: float
    amino_acids: AminoAcidProfile
    digestibility_diaas: AminoAcidProfile | None = None
    digestibility_diaas_source: str | None = None
    digestibility_pdcaas: float | None = None
    digestibility_pdcaas_source: str | None = None
    fdc_id: int | None = None
    data_type: str | None = None


class FoodOut(FoodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ScoreOut(BaseModel):
    method: str
    pattern_used: str
    score: float
    limiting_amino_acid: str
    per_aa_ratios: dict[str, float]
    digestibility_source: str | None = None
