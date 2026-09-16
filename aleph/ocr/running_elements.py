"""Conservative batch detection. Position alone never excludes a block."""
from collections import defaultdict
import re
from .engine import combined


def page_number(text):
    value = re.sub(r'''[\s״׳"'\-–().]''', '', text)
    if value.isdigit():
        return int(value)
    letters = 'אבגדהוזחטיכלמנסעפצקרשת'
    numbers = list(range(1, 10)) + list(range(10, 100, 10)) + [100, 200, 300, 400]
    if 1 <= len(value) <= 4 and all(c in letters for c in value):
        return sum(dict(zip(letters, numbers))[c] for c in value)
    return None


def filter_batch(results, options):
    from core import without_nikud
    if options.profile != 'torah' or options.include_repeated:
        return
    groups, pagination = defaultdict(list), defaultdict(list)
    for result in results:
        if not result.candidates:
            continue
        for block in result.candidates[0].blocks:
            if block.kind not in ('header_candidate', 'footer_candidate'):
                continue
            text = re.sub(r'\s+', ' ', without_nikud(block.candidates[block.selected].text)).strip()
            if not text:
                continue
            groups[(block.kind, text)].append((result.page, block))
            number = page_number(text)
            if number is not None:
                pagination[block.kind].append((result.page, number, block))
    if options.ignore_running_headers:
        for (_, text), matches in groups.items():
            if len({page for page, _ in matches}) >= 2 and page_number(text) is None:
                for _, block in matches:
                    block.included = False
                    block.exclusion_reason = 'repeated edge text across pages'
    if options.ignore_pagination:
        for values in pagination.values():
            offsets = defaultdict(list)
            for page, number, block in values:
                offsets[number - page].append((page, block))
            for matches in offsets.values():
                if len({page for page, _ in matches}) >= 3:
                    for _, block in matches:
                        block.included = False
                        block.exclusion_reason = 'sequential pagination across at least three pages'
    for result in results:
        if result.candidates and result.candidates[0].blocks:
            current = result.candidates[0]
            result.candidates[0] = combined(current.blocks, current.label)
