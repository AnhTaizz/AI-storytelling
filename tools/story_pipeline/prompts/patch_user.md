Requested scope: ${scope_label}

The script below is finished. Earlier full revisions fixed most problems but these are left,
and rewriting whole paragraphs again would put new mistakes into text that is already right.
Fix only these, with the smallest edits that make each statement true:

${findings}

Rules:
1. Each edit replaces one exact span ("old", copied character for character from the named
   paragraph, normally the whole sentence at fault) with corrected text ("new"). Use an empty
   "new" only to delete a sentence that cannot be made true.
2. Follow the source passages and briefs quoted with each problem; do not add any detail they
   do not give. Keep the voice and the pronouns of the surrounding text.
3. Do not touch any other text. One edit per problem; skip a problem only if the quoted span
   is already correct, and then leave it out.

Story Briefs (truth boundary):
${briefs}

Paragraphs:
${units}

Output exactly one JSON object that conforms to this JSON Schema. No Markdown, no code fences.

${schema}
