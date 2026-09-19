"""認証・権限 (spec 7.1, 10).

本番では企業SSO / OAuth2アクセストークンを利用する (spec 13: 実装前に確定)。
ここではローカル開発・検証用に、同じ権限モデル(ロール・会社スコープ)を
JWTで表現する簡易実装を提供する。/api/v1/auth/dev-token は開発専用であり、
本番では企業の認証基盤に置き換える。
"""
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt

from .config import get_settings

settings = get_settings()

CENTRAL_ADMIN = "CENTRAL_ADMIN"
COMPANY_HR = "COMPANY_HR"
VIEWER = "VIEWER"
API_ACCOUNT = "API_ACCOUNT"

ALL_COMPANIES = "*"


@dataclass
class CurrentUser:
    sub: str
    display_name: str
    roles: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)  # company codes, or ["*"]

    def has_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles)

    def can_access_company(self, company_code: str | None) -> bool:
        if self.has_role(CENTRAL_ADMIN):
            return True
        if ALL_COMPANIES in self.companies:
            return True
        if company_code is None:
            return False
        return company_code in self.companies

    def can_view_sensitive_fields(self) -> bool:
        """生年月日・備考の閲覧可否 (spec 5, 10)."""
        return self.has_role(CENTRAL_ADMIN, COMPANY_HR, API_ACCOUNT)


def create_access_token(user: CurrentUser) -> str:
    payload = {
        "sub": user.sub,
        "name": user.display_name,
        "roles": user.roles,
        "companies": user.companies,
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "UNAUTHENTICATED", "message": message, "field_errors": [], "request_id": None},
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])
    except JWTError:
        raise _unauthorized("Invalid or expired token")

    return CurrentUser(
        sub=payload.get("sub", "unknown"),
        display_name=payload.get("name", payload.get("sub", "unknown")),
        roles=payload.get("roles", []),
        companies=payload.get("companies", []),
    )


def require_roles(*roles: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(*roles):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": "Insufficient role for this operation",
                    "field_errors": [],
                    "request_id": None,
                },
            )
        return user

    return _dep


def require_company_access(user: CurrentUser, company_code: str | None) -> None:
    if not user.can_access_company(company_code):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "FORBIDDEN_COMPANY",
                "message": "No access to the specified company",
                "field_errors": [],
                "request_id": None,
            },
        )
