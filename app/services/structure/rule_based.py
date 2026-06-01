import re
from typing import List, Dict, Any, Optional
from app.schemas.structure import StructureElement
from app.services.structure.base import BaseStructureExtractor

class RuleBasedStructureExtractor(BaseStructureExtractor):
    """Rule-based document structure extractor using regex heuristics for RBI/SEBI documents."""

    def __init__(self):
        # Chapter pattern e.g. "CHAPTER I" or "Chapter 1" or "CHAPTER II - Introduction"
        self.chapter_pattern = re.compile(
            r"^\s*(CHAPTER|Chapter)\s+(?P<num>[IVXLCDM\d]+)(?:\s+[-:]?\s*(?P<rest>.*))?$",
            re.IGNORECASE
        )
        # Section pattern e.g. "1. Introduction" or "12. Customer Due Diligence"
        self.section_pattern = re.compile(
            r"^\s*(?P<num>\d+)\.\s+(?P<title>[A-Za-z].*)$"
        )
        # Subsection pattern e.g. "1.1 Applicability" or "12.1 Customer Acceptance Policy"
        self.subsection_pattern = re.compile(
            r"^\s*(?P<num>\d+\.\d+)\.?\s+(?P<title>[A-Za-z].*)$"
        )
        # Sub-subsection pattern e.g. "1.1.1 General"
        self.sub_subsection_pattern = re.compile(
            r"^\s*(?P<num>\d+\.\d+\.\d+)\.?\s+(?P<title>[A-Za-z].*)$"
        )
        # Clause pattern e.g. "(a) Customer", "(i) Small accounts", "a) Customer"
        self.clause_pattern = re.compile(
            r"^\s*(?P<num>\([a-zA-Z0-9]+\)|[a-zA-Z0-9]+\))\s+(?P<title>[A-Za-z].*)$"
        )
        # Page footers / headers exclusion
        self.page_number_pattern = re.compile(
            r"^\s*(Page|page)?\s*\d+\s*(of\s*\d+)?\s*$",
            re.IGNORECASE
        )

        # Regulators / metadata headers to ignore for document title lookup
        self.header_ignores = [
            "reserve bank of india",
            "securities and exchange board of india",
            "sebi",
            "rbi",
            "mumbai",
            "www.rbi.org.in",
            "www.sebi.gov.in",
            "department of",
            "notification",
            "circular"
        ]

    def _is_probable_heading(self, text: str) -> bool:
        """Heuristic check to differentiate section headings from body paragraphs starting with numbers."""
        # Headings shouldn't be extremely long
        if len(text) > 180:
            return False
        # Headings shouldn't contain multiple sentences (e.g. '. ' followed by uppercase letter)
        if len(re.findall(r"\.\s+[A-Z]", text)) > 0:
            return False
        return True

    def extract_structure(self, pages: List[Dict[str, Any]]) -> List[StructureElement]:
        elements: List[StructureElement] = []
        title_found = False
        pending_chapter_num: Optional[str] = None
        
        for page_idx, page in enumerate(pages):
            page_num = page.get("page_number", page_idx + 1)
            content = page.get("content", "")
            if not content:
                continue
                
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            
            for line in lines:
                # 1. Skip page number indicators
                if self.page_number_pattern.match(line):
                    continue
                    
                # 2. Extract Document Title on page 1
                if not title_found and page_num == 1:
                    lower_line = line.lower()
                    # Skip common headers/regulator names
                    should_ignore = False
                    for ignore in self.header_ignores:
                        if ignore in lower_line:
                            if len(line) < len(ignore) + 15:
                                should_ignore = True
                                break
                    
                    # Also ignore reference number lines
                    if re.search(r"rbi/\d{4}|sebi/|no\.|date\b", lower_line):
                        should_ignore = True
                        
                    if not should_ignore and len(line) > 5:
                        elements.append(StructureElement(
                            type="title",
                            title=line,
                            page=page_num,
                            level=0,
                            numbering=None
                        ))
                        title_found = True
                        continue
                
                # 3. Handle pending Chapter title from a previous line
                if pending_chapter_num is not None:
                    elements.append(StructureElement(
                        type="chapter",
                        title=line,
                        page=page_num,
                        level=1,
                        numbering=f"CHAPTER {pending_chapter_num}"
                    ))
                    pending_chapter_num = None
                    continue
                    
                # 4. Match Chapter
                chap_match = self.chapter_pattern.match(line)
                if chap_match:
                    num = chap_match.group("num")
                    rest = chap_match.group("rest")
                    if rest and rest.strip():
                        elements.append(StructureElement(
                            type="chapter",
                            title=rest.strip(),
                            page=page_num,
                            level=1,
                            numbering=f"CHAPTER {num}"
                        ))
                    else:
                        pending_chapter_num = num
                    continue
                    
                # 5. Match Sub-subsection
                sub_sub_match = self.sub_subsection_pattern.match(line)
                if sub_sub_match:
                    num = sub_sub_match.group("num")
                    title = sub_sub_match.group("title").strip()
                    if self._is_probable_heading(title):
                        elements.append(StructureElement(
                            type="clause",
                            title=title,
                            page=page_num,
                            level=4,
                            numbering=num
                        ))
                        continue
                    
                # 6. Match Subsection
                sub_match = self.subsection_pattern.match(line)
                if sub_match:
                    num = sub_match.group("num")
                    title = sub_match.group("title").strip()
                    if self._is_probable_heading(title):
                        elements.append(StructureElement(
                            type="subsection",
                            title=title,
                            page=page_num,
                            level=3,
                            numbering=num
                        ))
                        continue
                    
                # 7. Match Section
                sec_match = self.section_pattern.match(line)
                if sec_match:
                    num = sec_match.group("num")
                    title = sec_match.group("title").strip()
                    if self._is_probable_heading(title):
                        elements.append(StructureElement(
                            type="section",
                            title=title,
                            page=page_num,
                            level=2,
                            numbering=num
                        ))
                        continue
                    
                # 8. Match Clause
                clause_match = self.clause_pattern.match(line)
                if clause_match:
                    num = clause_match.group("num")
                    title = clause_match.group("title").strip()
                    if self._is_probable_heading(title):
                        elements.append(StructureElement(
                            type="clause",
                            title=title,
                            page=page_num,
                            level=5,
                            numbering=num
                        ))
                        continue
                    
        return elements
