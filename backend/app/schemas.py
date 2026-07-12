from pydantic import BaseModel, ConfigDict, Field


class AminoAcidProfile(BaseModel):
    histidine: float
    isoleucine: float
    leucine: float
    lysine: float
    met_cys: float = Field(description="methionine + cysteine")
    phe_tyr: float = Field(description="phenylalanine + tyrosine")
    threonine: float
    tryptophan: float
    valine: float


class FoodCreate(BaseModel):
    name: str
    protein_g_per_100g: float
    amino_acids: AminoAcidProfile
    digestibility_diaas: AminoAcidProfile | None = None
    digestibility_pdcaas: float | None = None


class FoodOut(FoodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ScoreOut(BaseModel):
    method: str
    pattern_used: str
    score: float
    limiting_amino_acid: str
    per_aa_ratios: dict[str, float]
