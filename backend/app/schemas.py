"""请求/响应 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---- 试验 ----
class CurvePointIn(BaseModel):
    temp_c: float = Field(..., description="馏出温度 ℃（换算到常压）")
    recovered_pct: float = Field(..., ge=0, le=100, description="累积回收体积百分比")


class DensityRowIn(BaseModel):
    temp_c: float = Field(..., description="馏出段代表温度/段中点 ℃")
    density_g_cm3: float = Field(..., gt=0, le=2.5)


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sample_id: str | None = Field(default=None, max_length=100)
    feed_density_g_cm3: float = Field(..., gt=0, le=2.5)
    residue_density_g_cm3: float | None = Field(default=None, gt=0, le=2.5)
    conditions: dict = Field(default_factory=dict)
    points: list[CurvePointIn] = Field(min_length=2)
    density_rows: list[DensityRowIn] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("points")
    @classmethod
    def _points_not_empty(cls, v: list[CurvePointIn]) -> list[CurvePointIn]:
        if len(v) < 2:
            raise ValueError("蒸馏曲线至少需要 2 个点")
        return v


class ExperimentOut(BaseModel):
    id: int
    name: str
    sample_id: str | None
    feed_density_g_cm3: float
    residue_density_g_cm3: float | None = None
    conditions: dict
    points: list[dict]
    density_rows: list[dict]
    notes: str | None

    model_config = {"from_attributes": True}


# ---- 方案 ----
class CutIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_temp_c: float
    end_temp_c: float


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    basis: Literal["volume", "mass"] = "volume"
    cuts: list[CutIn] = Field(min_length=1)
    loss_pct: float = Field(default=0.0, ge=0, le=100)


class PlanOut(BaseModel):
    id: int
    experiment_id: int
    name: str
    basis: str
    cuts: list[dict]
    loss_pct: float
    result_snapshot: dict | None = None

    model_config = {"from_attributes": True}


# ---- 切点敏感性预览 ----
class SensitivityIn(BaseModel):
    """单切点温度扰动预览：同一套方案规则下计算原/下/上三个情景，不落库。"""

    plan: PlanIn
    cut_index: int = Field(..., ge=0, description="被扰动切点所在馏分的下标（从 0 起）")
    endpoint: Literal["start", "end"] = Field(..., description="扰动该馏分的初馏点还是终馏点")
    step_c: float = Field(..., gt=0, le=500, description="温度扰动步长 ℃（分别向下/向上各扰一次）")

    @model_validator(mode="after")
    def _cut_index_in_range(self) -> "SensitivityIn":
        if self.cut_index >= len(self.plan.cuts):
            raise ValueError("cut_index 超出当前方案的馏分数量")
        return self
