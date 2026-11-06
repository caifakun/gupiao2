import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginInput(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


class GroupInput(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def check_name(cls, name):
        name = name.strip()
        if not name or name.casefold() == "全部自选" or re.search(r"[\x00-\x1f\x7f]", name):
            raise ValueError("分组名称无效")
        return name

    @field_validator("id")
    @classmethod
    def check_id(cls, group_id):
        if group_id == "all":
            raise ValueError("全部自选不是可编辑分组")
        return group_id


class StockInput(StrictModel):
    id: str = Field(pattern=r"^(SH|SZ)\.[0-9]{6}$")
    market: Literal["SH", "SZ"]
    code: str = Field(pattern=r"^[0-9]{6}$")
    name: str = Field(max_length=40)
    group: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def check_identity(self):
        if self.id != f"{self.market}.{self.code}" or re.search(r"[\x00-\x1f\x7f]", self.name):
            raise ValueError("证券标识或名称无效")
        return self


class SettingsInput(StrictModel):
    view: Literal["list", "grid"] = "list"
    layout: Literal[2, 4, 6] = 6


class WorkspaceUpdate(StrictModel):
    expected_revision: int = Field(ge=0, le=9223372036854775806)
    groups: list[GroupInput] = Field(min_length=2, max_length=100)
    stocks: list[StockInput] = Field(max_length=300)
    settings: SettingsInput

    @model_validator(mode="after")
    def check_workspace(self):
        identities = {group.id for group in self.groups}
        names = {group.name.casefold() for group in self.groups}
        if len(identities) != len(self.groups) or len(names) != len(self.groups) or not {"focus", "watch"}.issubset(identities):
            raise ValueError("分组重复或默认分组缺失")
        if len({stock.id for stock in self.stocks}) != len(self.stocks):
            raise ValueError("自选股票重复")
        if any(stock.group not in identities for stock in self.stocks):
            raise ValueError("股票所属分组不存在")
        return self
