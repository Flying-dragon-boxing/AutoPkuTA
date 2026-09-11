#!/usr/bin/env python3
"""Fetch Blackboard assignment page text using pku3b's saved session."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from pku3b_session import BASE_URL, blackboard_session, ca_bundle, pku3b_cache_dir


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._skip_depth = 0
        self._current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v or "" for k, v in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")
        if tag == "a":
            self._current_href = attrs_dict.get("href", "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "a":
            self._current_href = ""
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        self.parts.append(text)
        if self._current_href:
            self.links.append({"text": text, "href": self._current_href})

    def text(self) -> str:
        raw = " ".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def ids_from_url(url: str) -> tuple[str, str]:
    qs = parse_qs(urlparse(url).query)
    course_id = qs.get("course_id", [""])[0]
    content_id = qs.get("content_id", [""])[0]
    if not course_id or not content_id:
        raise SystemExit("URL must contain course_id and content_id")
    return course_id, content_id


def likely_assignment_instructions(text: str) -> str:
    patterns = [
        (r"1\.\s*作业信息\s*(.*?)\s*2\.\s*作业提交", re.S),
        (r"作业信息\s*(.*?)\s*作业提交", re.S),
        (r"内容\s*(.*?)\s*作业提交", re.S),
    ]
    for pattern, flags in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = match.group(1).strip()
            if len(value) >= 20:
                return value
    return ""


def relevant_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen = set()
    for item in links:
        text = item.get("text", "")
        href = item.get("href", "")
        haystack = f"{text} {href}".lower()
        if not any(ext in haystack for ext in [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".zip", ".rar", ".7z"]):
            continue
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def safe_name(value: str) -> str:
    value = html.unescape(value)
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", value).strip("_") or "attachment"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Blackboard assignment URL")
    parser.add_argument("--course-id")
    parser.add_argument("--content-id")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--download-attachments", action="store_true")
    args = parser.parse_args()

    if args.url:
        course_id, content_id = ids_from_url(args.url)
        url = args.url
    else:
        course_id = args.course_id
        content_id = args.content_id
        if not course_id or not content_id:
            raise SystemExit("Provide --url or both --course-id and --content-id")
        url = (
            BASE_URL
            + "/webapps/assignment/uploadAssignment"
            + f"?content_id={content_id}&course_id={course_id}&group_id=&mode=cpview"
        )

    cache_dir = pku3b_cache_dir()
    try:
        session = blackboard_session(cache_dir, accept="text/html,application/xhtml+xml,*/*")
    except RuntimeError as exc:
        raise SystemExit(f"{exc}. Run `python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh`.") from exc

    response = session.get(url, timeout=30, allow_redirects=True, verify=ca_bundle(cache_dir))
    if not response.ok:
        raise SystemExit(f"GET assignment page failed: {response.status_code} {response.text[:200]}")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    html_path = outdir / "assignment_page.html"
    html_path.write_text(response.text, encoding=response.encoding or "utf-8", errors="replace")

    parser_html = VisibleTextParser()
    parser_html.feed(response.text)
    visible_text = parser_html.text()
    instructions = likely_assignment_instructions(visible_text)
    attachments = relevant_links(parser_html.links)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""

    downloaded: list[dict[str, str]] = []
    if args.download_attachments and attachments:
        attachment_dir = outdir / "attachments"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(attachments, start=1):
            href = urljoin(BASE_URL, item["href"])
            name = safe_name(item.get("text") or Path(urlparse(href).path).name or f"attachment_{index}")
            if not Path(name).suffix and Path(urlparse(href).path).suffix:
                name += Path(urlparse(href).path).suffix
            target = attachment_dir / name
            r = session.get(href, timeout=90, allow_redirects=True, verify=ca_bundle(cache_dir))
            if r.ok and r.content:
                target.write_bytes(r.content)
                record = {"text": item.get("text", ""), "href": href, "path": str(target), "status": str(r.status_code)}
                if target.suffix.lower() == ".pdf" and shutil.which("pdftotext"):
                    text_path = target.with_suffix(target.suffix + ".txt")
                    run = subprocess.run(["pdftotext", "-layout", str(target), str(text_path)], capture_output=True, text=True, check=False)
                    if run.returncode == 0 and text_path.exists():
                        record["text_path"] = str(text_path)
                    else:
                        record["text_extract_error"] = (run.stderr or run.stdout or f"exit {run.returncode}")[-500:]
                downloaded.append(record)
            else:
                downloaded.append({"text": item.get("text", ""), "href": href, "path": "", "status": str(r.status_code)})

    context = {
        "course_id": course_id,
        "content_id": content_id,
        "url": url,
        "final_url": response.url,
        "title": title,
        "instructions": instructions,
        "attachments": attachments,
        "downloaded_attachments": downloaded,
        "text": visible_text,
        "links": parser_html.links,
    }
    (outdir / "assignment_context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2))

    md = [
        f"# Assignment Context",
        "",
        f"- course_id: `{course_id}`",
        f"- content_id: `{content_id}`",
        f"- title: {title or '(none)'}",
        f"- url: {url}",
        "",
        "## Likely Assignment Instructions",
        "",
        instructions or "(not isolated; use full visible text below)",
        "",
        "## Visible Page Text",
        "",
        visible_text or "(no visible text extracted)",
    ]
    if attachments:
        md.extend(["", "## Relevant Attachment Links", ""])
        for item in attachments:
            md.append(f"- {item['text']}: {urljoin(BASE_URL, item['href'])}")
    if downloaded:
        md.extend(["", "## Downloaded Attachments", ""])
        for item in downloaded:
            suffix = f" (text: {item['text_path']})" if item.get("text_path") else ""
            md.append(f"- {item['text']}: {item['path'] or 'DOWNLOAD_FAILED'}{suffix}")
    if parser_html.links:
        md.extend(["", "## Links", ""])
        for item in parser_html.links[:100]:
            md.append(f"- {item['text']}: {item['href']}")
    (outdir / "assignment_context.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "out": str(outdir),
                "instruction_chars": len(instructions),
                "chars": len(visible_text),
                "links": len(parser_html.links),
                "attachments": len(attachments),
                "downloaded": len([item for item in downloaded if item.get("path")]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
