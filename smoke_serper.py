from __future__ import annotations

from synthex_platform.retrieval import SerperClient


def main():
    client = SerperClient()
    result = client.search('"Synthex" materials science', num=3)
    print("Cache hit:", result.cache_hit)
    print("Local usage:", client.usage())
    for i, item in enumerate((result.data.get("organic", []) or [])[:3], 1):
        print(f"{i}. {item.get('title')}")
        print("  ", item.get('link'))


if __name__ == "__main__":
    main()
