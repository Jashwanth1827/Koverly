import { useEffect } from "react";

const SITE_NAME = "Koverly";
const DEFAULT_DESCRIPTION =
  "Understand, manage, and use every insurance policy your family owns.";

/** Keep the document title and description in sync with the visible page. */
export function usePageMeta(title?: string, description?: string) {
  useEffect(() => {
    document.title = title ? `${title} | ${SITE_NAME}` : SITE_NAME;

    let tag = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    if (!tag) {
      tag = document.createElement("meta");
      tag.name = "description";
      document.head.appendChild(tag);
    }
    tag.content = description || DEFAULT_DESCRIPTION;
  }, [title, description]);
}
