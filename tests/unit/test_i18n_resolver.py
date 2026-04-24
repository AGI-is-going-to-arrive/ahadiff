from __future__ import annotations

from ahadiff.i18n import (
    locale_from_accept_language,
    normalize_locale,
    normalize_locale_preference,
    resolve_locale,
)


def test_normalize_locale_accepts_supported_bcp47_aliases() -> None:
    assert normalize_locale("en-AU") == "en"
    assert normalize_locale("zh") == "zh-CN"
    assert normalize_locale("zh_Hans_CN.UTF-8") == "zh-CN"
    assert normalize_locale("fr-FR") is None


def test_normalize_locale_preference_accepts_auto_and_supported_locales() -> None:
    assert normalize_locale_preference("auto") == "auto"
    assert normalize_locale_preference("zh-hans") == "zh-CN"
    assert normalize_locale_preference("en_US.UTF-8") == "en"
    assert normalize_locale_preference("de") is None


def test_accept_language_uses_quality_before_header_order() -> None:
    assert locale_from_accept_language("en;q=0.1, zh-CN;q=0.9") == "zh-CN"
    assert locale_from_accept_language("fr-FR, en-AU;q=0.8") == "en"
    assert locale_from_accept_language("zh-CN;q=0, en;q=0.5") == "en"


def test_resolve_locale_contract_priority_chain() -> None:
    assert (
        resolve_locale(
            cookie_lang="en",
            accept_language="zh-CN",
            cli_lang="zh-CN",
            config_lang="zh-CN",
            env={"LANG": "zh_CN.UTF-8"},
        )
        == "en"
    )
    assert (
        resolve_locale(
            accept_language="zh-CN",
            cli_lang="en",
            config_lang="en",
            env={"LANG": "en_US.UTF-8"},
        )
        == "zh-CN"
    )
    assert resolve_locale(cli_lang="zh", config_lang="en", env={"LANG": "en_US.UTF-8"}) == "zh-CN"
    assert resolve_locale(config_lang="zh-CN", env={"LANG": "en_US.UTF-8"}) == "zh-CN"
    assert resolve_locale(config_lang="auto", env={"LANG": "zh_CN.UTF-8"}) == "zh-CN"
    assert resolve_locale(config_lang="auto", env={"LANG": "fr_FR.UTF-8"}) == "en"
