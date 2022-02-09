#!/usr/bin/env python3

from argparse import ArgumentParser
from enum import Enum
from pathlib import Path
from textwrap import dedent
from typing import Any, List, Optional, Union
import json
import sys


class DifferenceStyle(Enum):
    ABSOLUTE = 'absolute'
    RELATIVE = 'relative'
    HUMAN_READABLE = 'human-readable'

class OutputFormat(Enum):
    JSON = 'json'
    MARKDOWN = 'markdown'


class ValidationError(Exception):
    pass


class CommandLineError(ValidationError):
    pass


class BenchmarkDiffer:
    DEFAULT_RELATIVE_PRECISION = 4
    DEFAULT_DIFFERENCE_STYLE = DifferenceStyle.HUMAN_READABLE
    DEFAULT_OUTPUT_FOMAT = OutputFormat.MARKDOWN

    difference_style: DifferenceStyle
    relative_precision: Optional[int]
    output_format: OutputFormat

    def __init__(
        self,
        difference_style: DifferenceStyle = DEFAULT_DIFFERENCE_STYLE,
        relative_precision: Optional[int] = DEFAULT_RELATIVE_PRECISION,
        output_format: Optional[int] = DEFAULT_OUTPUT_FOMAT,
    ):
        self.difference_style = difference_style
        self.relative_precision = relative_precision
        self.output_format = output_format

    def run(self, before: Any, after: Any) -> Optional[Union[dict, str, int, float]]:
        if not isinstance(before, dict) or not isinstance(after, dict):
            return self._diff_scalars(before, after)

        if before.get('version') != after.get('version'):
            return self._humanize_diff('!V')

        diff = {}
        for key in (set(before) | set(after)) - {'version'}:
            value_diff = self.run(before.get(key), after.get(key))
            if value_diff not in [None, {}]:
                diff[key] = value_diff

        return diff

    def _diff_scalars(self, before: Any, after: Any) -> Optional[Union[str, int, float]]:
        assert not isinstance(before, dict) or not isinstance(after, dict)

        if before is None and after is None:
            return {}
        if before is None:
            return self._humanize_diff('!B')
        if after is None:
            return self._humanize_diff('!A')
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            return self._humanize_diff('!T')

        number_diff = self._diff_numbers(before, after)
        if self.difference_style != DifferenceStyle.HUMAN_READABLE:
            return number_diff

        return self._humanize_diff(number_diff)

    def _diff_numbers(self, value_before: int, value_after: int,) -> Union[str, int, float]:
        if self.difference_style == DifferenceStyle.ABSOLUTE:
            diff = value_after - value_before
            if isinstance(diff, float) and diff.is_integer():
                diff = int(diff)

            return diff

        if value_before == 0:
            if value_after > 0:
                return '+INF'
            elif value_after < 0:
                return '-INF'
            else:
                return 0

        diff = (value_after - value_before) / abs(value_before)
        if self.relative_precision is not None:
            rounded_diff = round(diff, self.relative_precision)
            if rounded_diff == 0 and diff < 0:
                diff = '-0'
            elif rounded_diff == 0 and diff > 0:
                diff = '+0'
            else:
                diff = rounded_diff

        if isinstance(diff, float) and diff.is_integer():
            diff = int(diff)

        return diff

    def _humanize_diff(self, diff: Union[str, int, float]) -> str:
        def wrap(value, symbol):
            return f"{symbol}{value}{symbol}"

        markdown = self.output_format == OutputFormat.MARKDOWN

        if isinstance(diff, str) and diff.startswith('!'):
            return wrap(diff, '`' if markdown else '')

        if isinstance(diff, (int, float)):
            value = diff * 100
            if isinstance(value, float) and self.relative_precision is not None:
                # The multiplication can result in new significant digits appearing. We need to reround.
                # NOTE: round() works fine with negative precision.
                value = round(value, self.relative_precision - 2)
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
            suffix = ''
            prefix = ''
            if diff < 0:
                prefix = ''
                suffix += ' ✅'
            elif diff > 0:
                prefix = '+'
                suffix += ' ❌'
            important = (diff != 0)
        else:
            value = diff
            important = False
            prefix = ''
            suffix = ''

        return wrap(
            wrap(
                f"{prefix}{value}%{suffix}",
                '`' if markdown else ''
            ),
            '**' if important and markdown else ''
        )


class MarkdownDiffFormatter:
    LEGEND = dedent("""
        `!V` = version mismatch
        `!B` = no value in the "before" version
        `!A` = no value in the "after" version
        `!T` = one or both values were not numeric and could not be compared
        `-0` = very small negative value rounded to zero
        `+0` = very small positive value rounded to zero
    """)

    @classmethod
    def run(cls, diff: dict):
        sorted_preset_names = sorted(cls._find_all_preset_names(diff))
        sorted_attribute_names = sorted(cls._find_all_attribute_names(diff))
        sorted_project_names = sorted(project for project in diff)

        project_column_width = max(len(project) for project in diff)

        output = ''
        for preset in sorted_preset_names:
            column_widths = [project_column_width] + [
                max(
                    len(attribute),
                    max(
                        len(cls._cell_content(diff, project, preset, attribute))
                        for project in sorted_project_names
                    )
                )
                for attribute in sorted_attribute_names
            ]
            output += f'\n### `{preset}`\n'
            output += cls._format_data_row(['project'] + sorted_attribute_names, column_widths) + '\n'
            output += cls._format_separator_row(column_widths) + '\n'

            for project in sorted_project_names:
                attribute_values = [
                    cls._cell_content(diff, project, preset, attribute)
                    for attribute in sorted_attribute_names
                ]
                output += cls._format_data_row([project] + attribute_values, column_widths) + '\n'

        output += f'\n{cls.LEGEND}\n'
        return output

    @classmethod
    def _find_all_preset_names(cls, diff: dict):
        return {
            preset
            for project, project_diff in diff.items()
            if isinstance(project_diff, dict)
            for preset in project_diff
        }

    @classmethod
    def _find_all_attribute_names(cls, diff: dict):
        return {
            attribute
            for project, project_diff in diff.items()
            if isinstance(project_diff, dict)
            for preset, preset_diff in project_diff.items()
            if isinstance(preset_diff, dict)
            for attribute in preset_diff
        }

    @classmethod
    def _cell_content(cls, diff: dict, project: str, preset: str, attribute: str):
        assert project in diff

        if isinstance(diff[project], str):
            return diff[project]
        if not preset in diff[project]:
            return ''
        if isinstance(diff[project][preset], str):
            return diff[project][preset]
        if not attribute in diff[project][preset]:
            return ''

        return diff[project][preset][attribute]

    @classmethod
    def _format_separator_row(cls, widths: List[int]):
        return '|:' + ':|-'.join('-' * width for width in widths) + ':|'

    @classmethod
    def _format_data_row(cls, cells: List[str], widths: List[int]):
        assert len(cells) == len(widths)

        return '| ' + ' | '.join(cell.rjust(width) for cell, width in zip(cells, widths)) + ' |'


def process_commandline() -> dict:
    script_description = (
        "Compares summarized benchmark reports and outputs JSON with the same structure but listing only differences. "
        "Can also print the output as markdown table and format the values to make differences stand out more."
    )

    parser = ArgumentParser(description=script_description)
    parser.add_argument(dest='report_before', help="Path to a JSON file containing benchmark results from before the change.")
    parser.add_argument(dest='report_after', help="Path to a JSON file containing benchmark results from after the change.")
    parser.add_argument(
        '--style',
        dest='difference_style',
        default=BenchmarkDiffer.DEFAULT_DIFFERENCE_STYLE.value,
        choices=[s.value for s in DifferenceStyle],
        help="How to present numeric differences."
    )
    # NOTE: Negative values are valid for precision. round() handles them in a sensible way.
    parser.add_argument(
        '--precision',
        dest='relative_precision',
        type=int,
        default=BenchmarkDiffer.DEFAULT_RELATIVE_PRECISION,
        help=(
            "Number of significant digits for relative differences. "
            f"Note that with --style={DifferenceStyle.HUMAN_READABLE.value} the rounding is applied "
            "**before** converting the value to a percentage so you need to add 2. "
            "Has no effect when used together with --style={DifferenceStyle.ABSOLUTE.value}."
        )
    )
    parser.add_argument(
        '--output-format',
        dest='output_format',
        choices=[o.value for o in OutputFormat],
        default=BenchmarkDiffer.DEFAULT_OUTPUT_FOMAT,
        help="The format to use for the diff."
    )
    return parser.parse_args()


def main():
    options = process_commandline()
    difference_style = DifferenceStyle(options.difference_style)
    output_format = OutputFormat(options.output_format)
    try:
        differ = BenchmarkDiffer(difference_style, options.relative_precision, output_format)
        diff = differ.run(
            json.loads(Path(options.report_before).read_text('utf-8')),
            json.loads(Path(options.report_after).read_text('utf-8')),
        )

        if output_format == OutputFormat.JSON:
            print(json.dumps(diff, indent=4))
        else:
            assert output_format == OutputFormat.MARKDOWN
            print(MarkdownDiffFormatter.run(diff))

        return 0
    except CommandLineError as exception:
        print(f"{exception}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
