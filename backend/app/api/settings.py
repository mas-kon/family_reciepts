from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.api.schemas import Ok
from app.db.seed import translate_categories
from app.db.session import get_session
from app.i18n import LANGUAGE_NAMES, LANGUAGES, current_language, set_language, t

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(current_viewer)])


class LanguageOption(BaseModel):
    code: str
    name: str


class LanguageOut(BaseModel):
    language: str
    options: list[LanguageOption]


class LanguageIn(BaseModel):
    language: str


@router.get("/settings/language", response_model=LanguageOut)
async def get_language():
    return {
        "language": current_language(),
        "options": [{"code": c, "name": LANGUAGE_NAMES[c]} for c in LANGUAGES],
    }


@router.put("/settings/language", response_model=Ok)
async def put_language(data: LanguageIn, session: AsyncSession = Depends(get_session)):
    if data.language not in LANGUAGES:
        raise HTTPException(422, t("settings.language_unsupported"))
    await set_language(session, data.language)
    await translate_categories(session, data.language)
    return Ok()
