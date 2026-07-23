"""fhir_utils 共用函式的單元測試。"""

from fhir_copilot.fhir_utils import datetime_sort_key


def test_datetime_sort_key_orders_by_true_time_not_lexicographic_string() -> None:
    """迴歸測試(M2 審查發現):真實 Synthea 資料同一病患跨年份混用 -04:00/-05:00
    位移,直接比字串排序會與實際時間相反。

    "09:30:00-05:00"(UTC 14:30)字串上小於 "10:00:00-04:00"(UTC 14:00),
    但 14:30 實際上比 14:00 晚——必須比較真正的 datetime,不能比字串。
    """
    later_but_lexicographically_smaller = "2020-03-08T09:30:00-05:00"  # UTC 14:30
    earlier_but_lexicographically_larger = "2020-03-08T10:00:00-04:00"  # UTC 14:00

    # 字串排序(錯的):後者字串「比較大」
    assert later_but_lexicographically_smaller < earlier_but_lexicographically_larger

    # 真正時間排序(對的):前者實際時間比較晚
    assert datetime_sort_key(later_but_lexicographically_smaller) > datetime_sort_key(
        earlier_but_lexicographically_larger
    )


def test_datetime_sort_key_missing_and_unparsable_sort_first_without_crashing() -> None:
    missing = datetime_sort_key(None)
    empty = datetime_sort_key("")
    garbage = datetime_sort_key("not-a-date")

    assert missing == empty == garbage
    assert missing < datetime_sort_key("2020-01-01T00:00:00+00:00")
