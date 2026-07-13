#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

DIGITS = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}

CJK_CHAR_RANGE = r"\u3400-\u9fff"


def normalize_acronyms(text: str) -> str:
    # Current Azure Dragon HD voices handle business acronyms directly.
    # Keep acronyms contiguous; adding spaces makes this TTS profile sound unnatural.
    return text


def normalize_commas(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


def year_to_cn(year: str) -> str:
    return "".join(DIGITS[d] for d in year)


def int_to_cn(num: int) -> str:
    if num == 0:
        return "零"

    units = ["", "十", "百", "千"]
    group_units = ["", "万", "亿", "兆"]

    def four_digit_to_cn(n: int) -> str:
        parts: list[str] = []
        zero_pending = False
        digits = [n // 1000, (n // 100) % 10, (n // 10) % 10, n % 10]
        for index, digit in enumerate(digits):
            place = 3 - index
            if digit == 0:
                if parts:
                    zero_pending = True
                continue
            if zero_pending:
                parts.append("零")
                zero_pending = False
            parts.append(DIGITS[str(digit)] + units[place])
        result = "".join(parts)
        if 10 <= n < 20 and result.startswith("一十"):
            result = result[1:]
        return result

    groups: list[int] = []
    n = num
    while n:
        groups.append(n % 10000)
        n //= 10000

    parts = []
    zero_between = False
    for idx in range(len(groups) - 1, -1, -1):
        group = groups[idx]
        if group == 0:
            zero_between = True
            continue
        if parts and (zero_between or group < 1000):
            parts.append("零")
            zero_between = False
        parts.append(four_digit_to_cn(group) + group_units[idx])

    return "".join(parts)


def number_to_cn(value: str, *, measure: bool = False) -> str:
    value = value.replace(",", "")
    if "." in value:
        left, right = value.split(".", 1)
        return int_to_cn(int(left)) + "点" + "".join(DIGITS[d] for d in right)
    cn = int_to_cn(int(value))
    if measure and cn == "二":
        return "两"
    return cn


def amount_number_to_cn(value: str) -> str:
    cn = number_to_cn(value)
    if "." not in value and cn.startswith("二千"):
        return "两千" + cn[len("二千") :]
    return cn


def normalize_years(text: str) -> str:
    # 2018-2023 年 / 2018 到 2023 年 -> 二零一八到二零二三年
    text = re.sub(
        r"(?<![\d.])([12]\d{3})\s*(?:至|到|-|–|—|~)\s*([12]\d{3})\s*年",
        lambda m: f"{year_to_cn(m.group(1))}到{year_to_cn(m.group(2))}年",
        text,
    )
    # 2019 年 / 2019年度 -> 二零一九年 / 二零一九年度
    text = re.sub(
        r"(?<![\d.])([12]\d{3})\s*(年|年度)",
        lambda m: f"{year_to_cn(m.group(1))}{m.group(2)}",
        text,
    )
    return text


def normalize_dates(text: str) -> str:
    text = re.sub(
        r"(?<!\d)618\s*大促",
        "六一八大促",
        text,
    )
    text = re.sub(
        r"(?<!\d)(1[0-2]|0?[1-9])\s*月\s*([12]\d|3[01]|0?[1-9])\s*日",
        lambda m: f"{number_to_cn(m.group(1))}月{number_to_cn(m.group(2))}日",
        text,
    )
    text = re.sub(
        r"(?<!\d)(1[0-2]|0?[1-9])\s*月",
        lambda m: f"{number_to_cn(m.group(1))}月",
        text,
    )
    return text


def normalize_percentages(text: str) -> str:
    text = re.sub(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*%",
        lambda m: f"百分之{number_to_cn(m.group(1))}到百分之{number_to_cn(m.group(2))}",
        text,
    )
    text = re.sub(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*%",
        lambda m: f"百分之{number_to_cn(m.group(1))}",
        text,
    )
    return text


def normalize_money_and_units(text: str) -> str:
    currencies = "美元|美金|港元|人民币|澳元|欧元|元"
    big_units = "亿|万"
    measure_units = (
        "百升|分钟|小时|个月|"
        "倍|股|升|人|个|家|所|场|台|条|种|次|套|座|辆|件|位|名|点|年|天|周"
    )

    # 5.13 至 6.02 美元 -> 五点一三至六点零二美元
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:至|到|-|–|—|~)\s*(\d+(?:\.\d+)?)\s*({currencies})",
        lambda m: f"{number_to_cn(m.group(1))}至{number_to_cn(m.group(2))}{m.group(3)}",
        text,
    )
    # 83 亿至 98 亿美元 -> 八十三亿至九十八亿美元
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({big_units})\s*(?:至|到|-|–|—|~)\s*(\d+(?:\.\d+)?)\s*({big_units})?\s*({currencies})",
        lambda m: (
            f"{amount_number_to_cn(m.group(1))}{m.group(2)}至"
            f"{amount_number_to_cn(m.group(3))}{m.group(4) or m.group(2)}{m.group(5)}"
        ),
        text,
    )
    # 1 万 2 -> 一万二. Common shorthand for salary or price.
    text = re.sub(
        r"(?<![\d.])(\d+)\s*万\s*([1-9])(?=\D|$)",
        lambda m: f"{number_to_cn(m.group(1))}万{DIGITS[m.group(2)]}",
        text,
    )
    # 98 亿美元 / 1.80 欧元
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({big_units})?\s*({currencies})",
        lambda m: f"{amount_number_to_cn(m.group(1)) if m.group(2) else number_to_cn(m.group(1))}{m.group(2) or ''}{m.group(3)}",
        text,
    )
    # 16-18 倍 / 16 到 18 倍
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:至|到|-|–|—|~)\s*(\d+(?:\.\d+)?)\s*({measure_units})",
        lambda m: f"{number_to_cn(m.group(1), measure=True)}到{number_to_cn(m.group(2), measure=True)}{m.group(3)}",
        text,
    )
    # 1,626,526,000 股 / 27 所 / 60 多场
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*(多)?\s*({measure_units})",
        lambda m: f"{number_to_cn(m.group(1), measure=True)}{m.group(2) or ''}{m.group(3)}",
        text,
    )
    # 83 亿 / 98 亿 where no currency follows.
    text = re.sub(
        rf"(?<![\d.])(\d+(?:\.\d+)?)\s*({big_units})(?![一-龥]*元|美元|美金|港元|人民币|欧元)",
        lambda m: f"{amount_number_to_cn(m.group(1))}{m.group(2)}",
        text,
    )
    return text


def normalize_remaining_numbers(text: str) -> str:
    # Remaining short integers are usually counts or list numbers, not years.
    text = re.sub(
        r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])",
        lambda m: number_to_cn(m.group(0)),
        text,
    )
    return text


def normalize_tts_spacing(text: str) -> str:
    # Do not leave artificial spaces inside Chinese narration; Azure handles prosody better from plain text.
    return "\n".join(
        re.sub(rf"(?<=[{CJK_CHAR_RANGE}])[\t ]+(?=[{CJK_CHAR_RANGE}])", "", line)
        for line in text.splitlines()
    )


def normalize_phrase_boundaries(text: str) -> str:
    # Prevent Azure from merging "出，路" into the lexical word "出路".
    text = text.replace("钱我来出，路你们带着走。", "钱，我来出。路，你们带着走。")
    text = text.replace("钱，我来出，路，你们带着走。", "钱，我来出。路，你们带着走。")
    return text


def normalize_for_tts(text: str) -> str:
    normalized = normalize_commas(text)
    normalized = normalize_acronyms(normalized)
    normalized = normalize_years(normalized)
    normalized = normalize_dates(normalized)
    normalized = normalize_percentages(normalized)
    normalized = normalize_money_and_units(normalized)
    normalized = normalize_remaining_numbers(normalized)
    normalized = normalize_phrase_boundaries(normalized)
    normalized = normalize_tts_spacing(normalized)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(normalize_for_tts(text), encoding="utf-8")


if __name__ == "__main__":
    main()
