#!/usr/bin/env python3
"""预计算 YouTube 缩略图里的人脸位置，供分享卡片裁切定位（可选工具）。

需要 OpenCV：pip install opencv-python-headless。结果写入 tools/og-faces.json（入库），
brand.py 读取它；没有记录的缩略图按默认位置裁切。新增单集后可重跑本脚本补齐。
"""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / '.cache' / 'yt'
OUT = ROOT / 'og-faces.json'


def main():
    faces = json.loads(OUT.read_text()) if OUT.exists() else {}
    det = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    n_new = 0
    for p in sorted(CACHE.glob('*.jpg')):
        if p.stem in faces and '--force' not in sys.argv:
            continue
        img = cv2.imread(str(p))
        if img is None:
            continue
        h, w = img.shape[:2]
        if h * 16 > w * 9 + 8:  # 4:3 带黑边，裁回 16:9
            ch = w * 9 // 16
            y0 = (h - ch) // 2
            img = img[y0:y0 + ch]
            h = ch
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        found = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(w // 14, w // 14))
        if len(found):
            x, y, fw, fh = max(found, key=lambda r: r[2] * r[3])
            faces[p.stem] = [round((x + fw / 2) / w, 3), round((y + fh / 2) / h, 3)]
        else:
            faces[p.stem] = None
        n_new += 1
    OUT.write_text(json.dumps(faces, separators=(',', ':'), sort_keys=True))
    hit = sum(1 for v in faces.values() if v)
    print(f'faces: {len(faces)} thumbs, {hit} with a face, {n_new} newly scanned')


if __name__ == '__main__':
    main()
