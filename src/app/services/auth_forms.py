"""
src/app/services/auth_forms.py

원본 accounts/signup.html, login.html 은 Django Form 의 BoundField 를 순회하며
렌더링합니다. 템플릿을 원본 그대로 유지하기 위해 동일한 속성(name, label, value,
errors, id_for_label, field.widget.input_type)을 제공하는 최소 호환 객체를 둡니다.

Django Form 전체를 재현하지 않습니다. 검증은 API 계층(Pydantic)이 담당하고,
본 모듈은 화면 렌더링과 오류 표시에만 관여합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from markupsafe import Markup, escape


@dataclass
class Choice:
    """RadioSelect 각 항목. 템플릿에서 {% for choice in field %} 로 순회합니다."""

    name: str
    value: str
    choice_label: str
    checked: bool = False

    @property
    def id_for_label(self) -> str:
        return f"id_{self.name}_{self.value}"

    @property
    def tag(self) -> Markup:
        checked = " checked" if self.checked else ""
        # 보간값을 전부 escape 한 뒤에만 Markup 으로 감쌉니다. Markup 은 Jinja
        # 자동 이스케이프를 건너뛰므로 원문을 그대로 넣으면 HTML 주입이 됩니다.
        return Markup(  # nosec B704
            f'<input type="radio" name="{escape(self.name)}" value="{escape(self.value)}" '
            f'id="{escape(self.id_for_label)}" class="peer sr-only"{checked}>'
        )


@dataclass
class WidgetSpec:
    input_type: str = "text"


@dataclass
class FieldSpec:
    widget: WidgetSpec = field(default_factory=WidgetSpec)


@dataclass
class BoundField:
    name: str
    label: str
    value: Any = ""
    errors: list[str] = field(default_factory=list)
    input_type: str = "text"
    hidden: bool = False
    choices: tuple[tuple[str, str], ...] = ()

    @property
    def id_for_label(self) -> str:
        return f"id_{self.name}"

    @property
    def field(self) -> FieldSpec:
        return FieldSpec(WidgetSpec(self.input_type))

    def __iter__(self):
        """ChoiceField 를 {% for choice in field %} 로 순회하기 위한 지원."""
        for value, label in self.choices:
            yield Choice(
                name=self.name,
                value=value,
                choice_label=label,
                checked=str(self.value) == value,
            )

    def __str__(self) -> str:
        """{{ form.birth_y }} 처럼 필드를 직접 출력할 때의 위젯 렌더링."""
        # value 는 제출된 폼 데이터입니다. 오류 재렌더 시 그대로 돌아오므로
        # escape 없이 Markup 에 넣으면 반사형 XSS 가 됩니다.
        if self.hidden:
            value = "" if self.value is None else self.value
            return Markup(  # nosec B704
                f'<input type="hidden" name="{escape(self.name)}" '
                f'id="{escape(self.id_for_label)}" value="{escape(value)}">'
            )
        return Markup(  # nosec B704
            f'<input type="{escape(self.input_type)}" name="{escape(self.name)}" '
            f'id="{escape(self.id_for_label)}" value="{escape(self.value or "")}">'
        )

    __html__ = __str__


# 원본 SignUpForm 의 필드 정의와 순서를 그대로 따릅니다.
SIGNUP_FIELDS: tuple[dict[str, Any], ...] = (
    {"name": "username", "label": "사용자 아이디", "input_type": "text"},
    {"name": "password1", "label": "비밀번호", "input_type": "password"},
    {"name": "password2", "label": "비밀번호 확인", "input_type": "password"},
    {"name": "nickname", "label": "닉네임", "input_type": "text"},
    {"name": "email", "label": "이메일", "input_type": "email"},
    {"name": "birth_date", "label": "생년월일", "input_type": "date"},
    {"name": "birth_y", "label": "출생 연도", "hidden": True},
    {"name": "birth_m", "label": "출생 월", "hidden": True},
    {"name": "birth_d", "label": "출생 일", "hidden": True},
    {
        "name": "gender",
        "label": "성별",
        "choices": (("M", "남"), ("F", "여")),
    },
    {"name": "agree_terms", "label": "이용약관 동의", "input_type": "checkbox"},
    {"name": "agree_privacy", "label": "개인정보처리방침 동의", "input_type": "checkbox"},
)


class RenderForm:
    """템플릿 렌더링 전용 폼. 제출 값과 오류를 그대로 되돌려 줍니다."""

    def __init__(
        self,
        specs: tuple[dict[str, Any], ...],
        data: dict[str, Any] | None = None,
        errors: dict[str, list[str]] | None = None,
        non_field_errors: list[str] | None = None,
    ):
        data = data or {}
        errors = errors or {}
        self._non_field_errors = non_field_errors or []
        self._fields: dict[str, BoundField] = {}
        for spec in specs:
            name = spec["name"]
            self._fields[name] = BoundField(
                name=name,
                label=spec["label"],
                value=data.get(name, ""),
                errors=errors.get(name, []),
                input_type=spec.get("input_type", "text"),
                hidden=spec.get("hidden", False),
                choices=spec.get("choices", ()),
            )

    def __iter__(self):
        return iter(self._fields.values())

    def __getattr__(self, item: str) -> BoundField:
        try:
            return self.__dict__["_fields"][item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    @property
    def errors(self) -> dict[str, list[str]]:
        """Django 와 동일하게 필드 오류에 더해 비필드 오류를 __all__ 로 포함합니다.

        원본 login.html 이 {% if form.errors %} 로 오류 배너를 띄우므로,
        비필드 오류만 있을 때도 참이 되어야 합니다.
        """
        collected = {
            name: bound.errors for name, bound in self._fields.items() if bound.errors
        }
        if self._non_field_errors:
            collected["__all__"] = list(self._non_field_errors)
        return collected

    @property
    def non_field_errors(self) -> list[str]:
        """Django 템플릿은 호출 없이 접근하므로 프로퍼티로 노출합니다."""
        return self._non_field_errors


def signup_form(data=None, errors=None, non_field_errors=None) -> RenderForm:
    return RenderForm(SIGNUP_FIELDS, data, errors, non_field_errors)


LOGIN_FIELDS: tuple[dict[str, Any], ...] = (
    {"name": "username", "label": "사용자 아이디", "input_type": "text"},
    {"name": "password", "label": "비밀번호", "input_type": "password"},
)


def login_form(data=None, errors=None, non_field_errors=None) -> RenderForm:
    return RenderForm(LOGIN_FIELDS, data, errors, non_field_errors)
