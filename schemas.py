"""Canlı veri toplamanın veritabanına yazdığı kayıtlar (rota maliyetine girer)."""
import datetime
from typing import Optional

from pydantic import BaseModel, Field


class QuakeCreateRequest(BaseModel):
    earthquake_id: str
    buyukluk: float = Field(..., gt=0)
    yer: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    deprem_zamani: datetime.datetime


class TrafficIncidentCreateRequest(BaseModel):
    olay_id: str = Field(..., min_length=1)
    kategori: str = Field(..., min_length=1)
    aciklama: Optional[str] = None
    gecikme_sn: Optional[int] = Field(None, ge=0)
    buyukluk: int = Field(0, ge=0, le=4)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
