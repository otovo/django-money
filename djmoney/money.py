from __future__ import annotations

import warnings
from types import MappingProxyType
from typing import overload, TYPE_CHECKING

from django.conf import settings
from django.db.models.expressions import Combinable, CombinedExpression
from django.utils import translation
from django.utils.deconstruct import deconstructible
from django.utils.html import avoid_wrapping, conditional_escape
from django.utils.safestring import mark_safe

import moneyed.l10n
from moneyed import Currency, Decimal, Money as DefaultMoney

from .settings import DECIMAL_PLACES, MONEY_FORMAT

if TYPE_CHECKING:
    from typing import Literal

__all__ = ["Money", "Currency"]


@deconstructible
class Money(DefaultMoney):
    """
    Extends functionality of Money with Django-related features.
    """

    use_l10n: bool | None = None

    def __init__(self, *args, format_options=None, **kwargs):
        self.decimal_places = kwargs.pop("decimal_places", DECIMAL_PLACES)
        self.format_options = MappingProxyType(format_options) if format_options is not None else None
        super().__init__(*args, **kwargs)

    def _copy_attributes(self, source, target):
        """Copy attributes to the new `Money` instance.

        This class stores extra bits of information about string formatting that the parent class doesn't have.
        The problem is that the parent class creates new instances of `Money` without in some of its methods and
        it does so without knowing about `django-money`-level attributes.
        For this reason, when this class uses some methods of the parent class that have this behavior, the resulting
        instances lose those attribute values.

        When it comes to what number of decimal places to choose, we take the maximum number.
        """
        selection = [
            getattr(candidate, "decimal_places", None)
            for candidate in (self, source)
            if getattr(candidate, "decimal_places", None) is not None
        ]
        if selection:
            target.decimal_places = max(selection)

    @overload
    def __add__(self, other: Money | DefaultMoney | Literal[0]) -> Money:
        ...

    @overload
    def __add__(self, other: Combinable) -> CombinedExpression:
        ...

    def __add__(self, other: Money | DefaultMoney | Combinable | Literal[0]) -> Money | CombinedExpression:
        if isinstance(other, Combinable):
            return other.__radd__(self.amount)
        other = maybe_convert(other, self.currency)
        result = super().__add__(other)
        self._copy_attributes(other, result)
        return result

    @overload
    def __sub__(self, other: Money | DefaultMoney | Literal[0]) -> Money:
        ...

    @overload
    def __sub__(self, other: Combinable) -> CombinedExpression:
        ...

    def __sub__(self, other: Money | DefaultMoney | Combinable | Literal[0]) -> Money | CombinedExpression:
        if isinstance(other, Combinable):
            return other.__rsub__(self.amount)
        other = maybe_convert(other, self.currency)
        result = super().__sub__(other)
        self._copy_attributes(other, result)
        return result

    @overload
    def __mul__(self, other: Money | DefaultMoney | Decimal | float | int) -> Money:
        ...

    @overload
    def __mul__(self, other: Combinable) -> CombinedExpression:
        ...

    def __mul__(self, other: Money | DefaultMoney | Decimal | float | int | Combinable) -> Money | CombinedExpression:
        if isinstance(other, Combinable):
            return other.__rmul__(self.amount)
        result = super().__mul__(other)
        self._copy_attributes(other, result)
        return result

    def __rmul__(self, other):
        return self.__mul__(other)

    def __radd__(self, other):
        return self.__add__(other)

    @overload
    def __truediv__(self, other: Money) -> Decimal:
        ...

    @overload
    def __truediv__(self, other: int | Decimal | float) -> Money:
        ...

    @overload
    def __truediv__(self, other: Combinable) -> CombinedExpression:
        ...

    def __truediv__(self, other: Money | Decimal | float | int | Combinable) -> Money | CombinedExpression | Decimal:
        if isinstance(other, Combinable):
            return other.__rtruediv__(self.amount)
        result = super().__truediv__(other)
        if isinstance(result, self.__class__):
            self._copy_attributes(other, result)
        return result

    def __rtruediv__(self, other):
        # Backported from py-moneyed, non released bug-fix
        # https://github.com/py-moneyed/py-moneyed/blob/c518745dd9d7902781409daec1a05699799474dd/moneyed/classes.py#L217-L218
        raise TypeError("Cannot divide non-Money by a Money instance.")

    @property
    def is_localized(self) -> bool:
        if self.use_l10n is None:
            # This definitely raises a warning in Django 4 - we want to ignore RemovedInDjango50Warning
            # However, we cannot ignore this specific warning class as it doesn't exist in older
            # Django versions
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore")
                setting = getattr(settings, "USE_L10N", True)
            return setting
        return self.use_l10n

    def __str__(self):
        format_options = {
            **MONEY_FORMAT,
            **(self.format_options or {}),
        }
        locale = get_current_locale()
        if locale:
            format_options["locale"] = locale
        return moneyed.l10n.format_money(self, **format_options)

    def __html__(self):
        return mark_safe(avoid_wrapping(conditional_escape(str(self))))

    def __round__(self, n=None):
        amount = round(self.amount, n)
        new = self.__class__(amount, self.currency)
        self._copy_attributes(self, new)
        return new

    def round(self, ndigits=0):
        new = super().round(ndigits)
        self._copy_attributes(self, new)
        return new

    def __pos__(self):
        new = super().__pos__()
        self._copy_attributes(self, new)
        return new

    def __neg__(self):
        new = super().__neg__()
        self._copy_attributes(self, new)
        return new

    def __abs__(self):
        new = super().__abs__()
        self._copy_attributes(self, new)
        return new

    def __rmod__(self, other):
        new = super().__rmod__(other)
        self._copy_attributes(self, new)
        return new

    # DefaultMoney sets those synonym functions
    # we overwrite the 'targets' so the wrong synonyms are called
    # Example: we overwrite __add__; __radd__ calls __add__ on DefaultMoney...


def get_current_locale():
    return translation.to_locale(
        translation.get_language()
        # get_language can return None starting from Django 1.8
        or settings.LANGUAGE_CODE
    )


def maybe_convert(value, currency):
    """
    Converts other Money instances to the local currency if `AUTO_CONVERT_MONEY` is set to True.
    """
    if getattr(settings, "AUTO_CONVERT_MONEY", False) and value.currency != currency:
        from .contrib.exchange.models import convert_money

        return convert_money(value, currency)
    return value
