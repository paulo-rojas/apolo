from typing import Any, Dict, List


def search_accessibility_tree(node: Dict[str, Any], text: str, found: List[Dict[str, Any]], path: str = ""):
    name = node.get("name") or ""
    role = node.get("role")
    if text.lower() in name.lower():
        found.append({"path": path, "name": name, "role": role})
    for i, child in enumerate(node.get("children", [])):
        search_accessibility_tree(child, text, found, path + f"/{i}")


def find_by_accessibility(page, text: str, max_results: int = 5):
    """Use Playwright accessibility snapshot to find nodes whose name contains text."""
    try:
        tree = page.accessibility.snapshot()
        found = []
        search_accessibility_tree(tree, text, found)
        return found[:max_results]
    except Exception:
        return []


def simple_text_locator_candidates(page, text: str, max_results: int = 5):
    try:
        locator = page.locator(f'text="{text}"')
        cnt = locator.count()
        results = []
        for i in range(min(cnt, max_results)):
            el = locator.nth(i)
            try:
                t = el.inner_text()
            except Exception:
                t = ""
            results.append({"index": i, "text": t})
        return results
    except Exception:
        return []
