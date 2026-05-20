import json
from pathlib import Path

ids = [
    'tpl_application_form_part_b_erasmus_bb_a_0cee53',
    'tpl_application_form_part_b_erasmus_bb_a_acb238',
    'tpl_application_form_part_b_erasmus_bb_a_932304',
    'tpl_application_form_part_b_erasmus_bb_a_c9fe58',
    'tpl_application_form_part_b_erasmus_bb_a_6e7c0b',
]

f = Path('data/chunks/Tpl_Application Form Part B ERASMUS BB and LSII_chunks.json')
chunks = json.loads(f.read_text(encoding='utf-8'))

for c in chunks:
    if c['chunk_id'] in ids:
        print(f"--- {c['section_title']}")
        print(f"    level   : {c['section_level']}")
        print(f"    content : [{c['content']}]")
        print()