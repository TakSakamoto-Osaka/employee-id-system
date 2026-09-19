"""開発用トークン発行 (spec 13: 本番はSSO/OAuth2に置き換える open item)。"""
from fastapi import APIRouter

from ..schemas import DevTokenRequest, DevTokenResponse
from ..security import CurrentUser, create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/dev-token", response_model=DevTokenResponse)
def issue_dev_token(payload: DevTokenRequest) -> DevTokenResponse:
    user = CurrentUser(
        sub=payload.sub,
        display_name=payload.display_name,
        roles=payload.roles,
        companies=payload.companies,
    )
    token = create_access_token(user)
    return DevTokenResponse(access_token=token)
