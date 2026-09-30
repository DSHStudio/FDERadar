"""Declare a bounded collection manifest from existing evidence URLs, not search snippets."""
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent


def prepare():
    candidates = {}
    corpus = ROOT.parent / '本体与FDE_数据底稿'
    for path in corpus.glob('*.json'):
        if path.name not in {'首批项目与披露记录.json', '技术资料记录.json', '交付组织与方法资料.json', '多媒体与研究资料.json', '学习加工记录.json'}:
            continue
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        def walk(node, record=None):
            if isinstance(node, dict):
                record = node if node.get('id') else (record or node)
                for key, child in node.items():
                    if key == 'url' and isinstance(child, str) and child.startswith(('https://', 'http://')):
                        parts = urlsplit(child)
                        url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
                        if url not in candidates:
                            candidates[url] = {'url':url, 'title': node.get('title') or record.get('title') or record.get('name') or url,
                                'channel': record.get('media_type') or ('案例原始材料' if path.name.startswith('首批') else '技术与交付材料'),
                                'track': 'case' if path.name.startswith('首批') else 'theory',
                                'discoveredFrom': path.name, 'recordId': record.get('id'),
                                'stage':'candidate', 'dshTested':False,
                                'caution':'历史底稿链接；本批重新采集成功前不算已取得原文。'}
                    walk(child, record)
            elif isinstance(node, list):
                for child in node: walk(child, record)
        walk(value)
    target = ROOT/'config'/'source-discovery-corpus-2026-09-28.json'
    target.write_text(json.dumps({'schema':'fde-radar.discovery/v1','createdAt':'2026-09-28',
        'scope':'历史底稿原始证据回填；时间范围包括经典案例和2026披露；不是市场全量',
        'candidates':list(candidates.values())},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'candidates':len(candidates),'file':str(target)}


if __name__ == '__main__':
    print(json.dumps(prepare(),ensure_ascii=False))
