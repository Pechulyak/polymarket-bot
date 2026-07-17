#!/usr/bin/env python3
# Отбор событий stream-json из mm.sh перед записью в лог: убрать "system",
# срезать "thinking", обрезать длинные tool_result. Экономит объём mm_executor.log.
import json
import sys

KEEP_TYPES = {"assistant", "user", "result"}
TRUNC_LIMIT = 2000
TRUNC_MARK = "[truncated]"


def truncate(text):
    if isinstance(text, str) and len(text) > TRUNC_LIMIT:
        return text[:TRUNC_LIMIT] + TRUNC_MARK
    return text


def filter_content_block(block):
    if not isinstance(block, dict):
        return block
    if block.get("type") == "tool_result":
        content = block.get("content")
        if isinstance(content, str):
            block = {**block, "content": truncate(content)}
        elif isinstance(content, list):
            new_items = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    item = {**item, "text": truncate(item["text"])}
                new_items.append(item)
            block = {**block, "content": new_items}
    return block


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            print(line, flush=True)
            continue

        if obj.get("type") not in KEEP_TYPES:
            continue

        message = obj.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), list):
            new_content = [
                filter_content_block(block)
                for block in message["content"]
                if not (isinstance(block, dict) and block.get("type") == "thinking")
            ]
            obj["message"] = {**message, "content": new_content}

        print(json.dumps(obj, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
