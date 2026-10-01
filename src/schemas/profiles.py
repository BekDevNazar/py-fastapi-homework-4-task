from datetime import date

from fastapi import UploadFile
from pydantic import BaseModel, field_validator, ConfigDict

from validation import (
    validate_name,
    validate_image,
    validate_gender,
    validate_birth_date,
)


class Profile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    info: str
    avatar: UploadFile

    @field_validator("first_name")
    @classmethod
    def check_first_name(cls, value: str):
        validate_name(value)
        return value.lower()

    @field_validator("last_name")
    @classmethod
    def check_last_name(cls, value: str):
        validate_name(value)
        return value.lower()

    @field_validator("gender")
    @classmethod
    def check_gender(cls, value: str):
        validate_gender(value)
        return value

    @field_validator("date_of_birth")
    @classmethod
    def check_date_of_birth(cls, value: date):
        validate_birth_date(value)
        return value

    @field_validator("info")
    @classmethod
    def check_info(cls, value: str):
        if not value.strip():
            raise ValueError(
                "Info field cannot be empty or contain only spaces."
            )
        return value

    @field_validator("avatar")
    @classmethod
    def check_avatar(cls, value: UploadFile):
        validate_image(value)
        return value


class ProfileResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str
    gender: str
    date_of_birth: date
    info: str
    avatar: str
