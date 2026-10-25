"""Short native labels put the export type and version before the scene title."""
import re


def export_label(scene_name, mode='static_entities'):
    title = str(scene_name).strip()
    version = re.search(r'(?<![A-Za-z0-9])v\s*(\d+(?:\.\d+)*)', title, re.I)
    suffix = 'V' + version.group(1) if version else ''
    if version:
        title = title[:version.start()] + title[version.end():]
    title = re.sub(r'^(?:StarScene)[\s_·-]*', '', title, flags=re.I)
    title = re.sub(r'静态|动态', '', title)
    title = title.strip(' .·_-') or '场景'
    label = ('静态' if mode == 'static_entities' else '动态') + suffix + '·' + title
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label).strip(' .')[:60]


def static_entity_label(name, export_name):
    version = re.match(r'静态(V\d+(?:\.\d+)*)?·', export_label(export_name))
    prefix = '静' + (version.group(1) or '') + '·'
    title = re.sub(r'^静(?:V\d+(?:\.\d+)*)?·', '', str(name))
    return (prefix + title)[:220]
