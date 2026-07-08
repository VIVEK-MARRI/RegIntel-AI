from typing import List, Set, Optional
from app.schemas.hierarchy import HierarchyNode


class HierarchyValidator:
    """Validator class ensuring structural and metadata integrity of the hierarchy tree."""

    def validate(self, root: HierarchyNode) -> List[str]:
        """Validates the hierarchy tree and returns a list of validation error/warning strings.

        If the returned list is empty, the tree is valid.
        """
        errors: List[str] = []
        seen_ids: Set[str] = set()

        self._traverse_and_validate(root, None, seen_ids, errors)
        return errors

    def _traverse_and_validate(
        self,
        node: HierarchyNode,
        parent: Optional[HierarchyNode],
        seen_ids: Set[str],
        errors: List[str],
    ) -> None:
        # 1. Title completeness check
        if not node.title or not node.title.strip():
            errors.append(
                f"Node '{node.node_id}' has an empty or whitespace-only title."
            )

        # 2. Duplicate Node ID check
        if node.node_id in seen_ids:
            errors.append(f"Duplicate node ID detected: '{node.node_id}'.")
        else:
            seen_ids.add(node.node_id)

        # 3. Parent-child relationship checks
        if parent is not None:
            # Level check
            if node.level <= parent.level:
                errors.append(
                    f"Level violation: Child node '{node.title}' (level {node.level}) "
                    f"must have a level greater than its parent '{parent.title}' (level {parent.level})."
                )

            # Page progression check
            if node.page < parent.page:
                errors.append(
                    f"Page progression violation: Child node '{node.title}' on page {node.page} "
                    f"is before parent '{parent.title}' on page {parent.page}."
                )

            # parent_id check
            if node.parent_id != parent.node_id:
                errors.append(
                    f"Parent ID mismatch: Node '{node.title}' has parent_id '{node.parent_id}' "
                    f"but is children of '{parent.node_id}'."
                )

        # Traverse children
        for child in node.children:
            self._traverse_and_validate(child, node, seen_ids, errors)
