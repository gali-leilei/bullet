"""FastAPI dependencies for authentication and authorization."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.models.user import User


async def get_current_user(request: Request) -> User:
    """Get the current authenticated user from session.

    Raises HTTPException 401 if not authenticated.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = await User.get(user_id)
    if not user:
        # Session contains invalid user ID, clear it
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


async def get_current_user_optional(request: Request) -> User | None:
    """Get the current user if authenticated, otherwise None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    user = await User.get(user_id)
    if not user or not user.is_active:
        return None

    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)]
) -> User:
    """Require admin role for the current user.

    Raises HTTPException 403 if not admin.
    """
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
AdminUser = Annotated[User, Depends(require_admin)]

