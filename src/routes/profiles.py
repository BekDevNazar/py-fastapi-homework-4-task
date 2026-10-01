from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Form, UploadFile, File
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette import status
from database import get_db, UserModel, UserProfileModel, UserGroupEnum

from config import get_jwt_auth_manager, get_s3_storage_client
from exceptions import TokenExpiredError, InvalidTokenError, S3ConnectionError, S3FileUploadError
from schemas.profiles import Profile, ProfileResponseSchema
from security.interfaces import JWTAuthManagerInterface
from storages import S3StorageInterface

router = APIRouter()


async def get_auth_payload(
    authorization: str | None = Header(default=None),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> dict:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is missing",
        )

    parts = authorization.split()

    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
        )

    try:
        return jwt_manager.decode_access_token(parts[1])
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Token has expired.")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


@router.post(
    "/users/{user_id}/profile/",
    response_model=ProfileResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    user_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    gender: str = Form(...),
    date_of_birth: date = Form(...),
    info: str = Form(...),
    avatar: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
    payload: dict = Depends(get_auth_payload),
    db: AsyncSession = Depends(get_db),
    s3_client: S3StorageInterface = Depends(get_s3_storage_client),
):

    current_user_id = payload.get("user_id")

    result = await db.execute(
        select(UserModel)
        .options(selectinload(UserModel.group))
        .where(UserModel.id == current_user_id)
    )
    current_user = result.scalar_one_or_none()
    if not current_user or not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active.",
        )

    if (
            current_user_id != user_id
            and current_user.group.name != UserGroupEnum.ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this profile.",
        )

    user_result = await db.execute(
        select(UserModel)
        .where(UserModel.id == user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )

    profile = await db.execute(select(UserProfileModel).where(UserProfileModel.user_id == user_id))
    is_profile = profile.scalar_one_or_none()

    if is_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile."
        )

    try:
        profile_data = Profile(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            info=info,
            avatar=avatar,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(
                include_context=False,
                include_input=False,
            ),
        ) from exc

    file_data = await profile_data.avatar.read()

    extension = profile_data.avatar.filename.rsplit(".", 1)[-1].lower()
    file_name = f"avatars/{user_id}_avatar.{extension}"

    try:
        await s3_client.upload_file(
            file_name=file_name,
            file_data=file_data,
        )
    except (S3ConnectionError, S3FileUploadError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later.",
        ) from exc

    avatar_url = await s3_client.get_file_url(file_name)

    new_profile = UserProfileModel(
        user_id=user_id,
        first_name=profile_data.first_name,
        last_name=profile_data.last_name,
        gender=profile_data.gender,
        date_of_birth=profile_data.date_of_birth,
        info=profile_data.info,
        avatar=file_name,
    )

    try:
        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the profile.",
        )

    response_data = ProfileResponseSchema.model_validate(new_profile)
    return response_data.model_copy(
        update={"avatar": avatar_url}
    )
