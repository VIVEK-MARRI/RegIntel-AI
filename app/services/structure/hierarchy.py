import uuid
import logging
from typing import List
from app.schemas.structure import StructureElement
from app.schemas.hierarchy import HierarchyNode

logger = logging.getLogger(__name__)


class HierarchyBuilder:
    """Builder class converting flat StructureElements into a nested navigable tree."""

    def build_hierarchy(
        self,
        document_id: uuid.UUID,
        fallback_title: str,
        elements: List[StructureElement],
    ) -> HierarchyNode:
        """Constructs a hierarchical tree from a list of flat, ordered StructureElements.

        Args:
            document_id: UUID of the parent document. Used to generate namespace stable node IDs.
            fallback_title: Fallback title of the document if no title element is found.
            elements: List of StructureElements parsed from the document in reading order.

        Returns:
            The root HierarchyNode of the document.
        """
        logger.info(
            f"Building hierarchy for document {document_id} from {len(elements)} elements"
        )

        # 1. Detect title and page from elements
        doc_title = fallback_title
        doc_page = 1

        for el in elements:
            if el.type == "title":
                doc_title = el.title
                doc_page = el.page
                break

        # 2. Initialize the root document node
        root_uuid = uuid.uuid5(uuid.UUID(str(document_id)), "root")
        root_node = HierarchyNode(
            node_id=str(root_uuid),
            node_type="document",
            title=doc_title,
            parent_id=None,
            page=doc_page,
            level=0,
            numbering=None,
            children=[],
        )

        stack: List[HierarchyNode] = [root_node]

        # 3. Build tree hierarchically using stack-based level comparison
        for el in elements:
            if el.type == "title":
                # Title is already handled as the root node
                continue

            # Pop from stack until the top of the stack has a level strictly less than current element
            while len(stack) > 1 and stack[-1].level >= el.level:
                stack.pop()

            parent = stack[-1]

            # Generate stable deterministic node ID using uuid.uuid5 based on tree path
            path_components = [p.numbering or p.title for p in stack[1:]] + [
                el.numbering or el.title
            ]
            path_string = " / ".join(path_components)
            node_uuid = uuid.uuid5(uuid.UUID(str(document_id)), path_string)

            node = HierarchyNode(
                node_id=str(node_uuid),
                node_type=el.type,
                title=el.title,
                parent_id=parent.node_id,
                page=el.page,
                level=el.level,
                numbering=el.numbering,
                children=[],
            )

            parent.children.append(node)
            stack.append(node)

        return root_node
