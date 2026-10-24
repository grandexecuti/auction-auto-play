#!/usr/bin/env python3
# auto_play.py - Windows ADB + OCR automation for a 900x1600 auction game.
# It enters matches, reads the estimated price, bids, settles and loops.
#
# Requirements: Windows 10/11, Python 3.9+, Pillow, adb, an emulator running
# the game at 900x1600 (the UI coordinates below are calibrated for that size).
import os, re, time, subprocess
from PIL import Image

ADB = os.environ.get('ADB', 'adb')
SERIAL = os.environ.get('SERIAL', '127.0.0.1:5555')
HERE = os.path.dirname(os.path.abspath(__file__))
FULL = os.path.join(HERE, 'screen.png')
CROP = os.path.join(HERE, 'crop.png')
OCR = os.path.join(HERE, 'ocr.ps1')
LOG = os.path.join(HERE, 'auto_play.log')

OFFSET = int(os.environ.get('OFFSET', '1000'))
AGGR = float(os.environ.get('AGGR', '1.0'))
MAX_BID = int(os.environ.get('MAX_BID', '5000'))
MIN_BID = 100
TARGET_MATCHES = int(os.environ.get('MATCHES', '0'))   # 0 = run forever
DRY = os.environ.get('DRY', '0') == '1'

def log(s):
    line = '%s %s' % (time.strftime('%H:%M:%S'), s)
    with open(LOG, 'a', encoding='utf8') as f:
        f.write(line + '\n')
    print(line, flush=True)

def sh(cmd, timeout=25):
    return subprocess.run([ADB, '-s', SERIAL] + cmd, capture_output=True, timeout=timeout)

def tap(x, y):
    if DRY:
        log('DRY tap %d,%d' % (x, y)); return
    try:
        sh(['shell', 'input', 'tap', str(x), str(y)])
    except Exception as e:
        log('tap err %r' % e)

def screencap():
    for _ in range(3):
        try:
            with open(FULL, 'wb') as f:
                r = subprocess.run([ADB, '-s', SERIAL, 'exec-out', 'screencap', '-p'],
                                   stdout=f, stderr=subprocess.DEVNULL, timeout=20)
            if r.returncode == 0 and os.path.getsize(FULL) > 1000:
                Image.open(FULL).load()
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def crop(box, out=CROP):
    try:
        im = Image.open(FULL)
        im.crop(box).save(out)
        return True
    except Exception:
        return False

def ocr(path=CROP):
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', OCR, '-Path', path], capture_output=True, text=True, timeout=30)
        return r.stdout.replace('\n', '').replace('\r', '').replace(' ', '')
    except Exception:
        return ''

def ocr_bottom():
    crop((0, 1310, 900, 1600))
    return ocr()

def ocr_center():
    crop((80, 480, 820, 1150))
    return ocr()

def ocr_est():
    pad = pad_open()
    boxes = ((150, 820, 760, 915),) if pad else ((150, 820, 760, 915), (150, 1000, 760, 1100))
    for box in boxes:
        if not crop(box):
            continue
        t = ocr().replace('，', ',')
        g = re.findall(r'[0-9][0-9,]*', t)
        if not g:
            continue
        v = max(g, key=len).replace(',', '')
        try:
            v = int(v)
        except Exception:
            continue
        if 100 <= v <= 100000000:
            return v
    return None

BID_BTN = (450, 1510)
START_BTN = (450, 1500)
SKIP_BTN = (450, 1450)
NEXT_BTN = (670, 1450)
BACK_BTN = (220, 1450)
DISMISS = (450, 1300)
RANK_BTN = (450, 1345)
CONFIRM_BTN = (650, 960)
LOGIN_BTN = (450, 1345)
ROOM_BTN = (780, 1220)

def pad_open():
    if not crop((0, 970, 900, 1130)):
        return False
    t = ocr()
    return ('出价高于' in t) or ('直接成交' in t) or ('确认出价' in t)

def enter_amount(v):
    for _ in range(9):
        tap(780, 1190)
        time.sleep(0.07)
    cols = {'1': 120, '2': 340, '3': 560, '4': 120, '5': 340, '6': 560,
            '7': 120, '8': 340, '9': 560, '0': 120}
    rows = {'1': 1190, '2': 1190, '3': 1190, '4': 1290, '5': 1290, '6': 1290,
            '7': 1390, '8': 1390, '9': 1390, '0': 1490}
    for ch in str(v):
        if ch in cols:
            tap(cols[ch], rows[ch])
            time.sleep(0.12)

def bid_amount(amount, est=None):
    log('bid %.0f (est %s)' % (amount, est if est is not None else '?'))
    opened = False
    for _ in range(3):
        if pad_open():
            opened = True
            break
        tap(*BID_BTN)
        time.sleep(1.3)
        screencap()
    if not opened and not pad_open():
        log('pad failed, will retry next round')
        return False
    enter_amount(amount)
    time.sleep(0.4)
    tap(770, 1052)
    time.sleep(1.5)
    log('submitted')
    return True

def main():
    log('# start target=%s aggr=%.2f max_bid=%d offset=%d dry=%s' %
        ('inf' if TARGET_MATCHES == 0 else TARGET_MATCHES, AGGR, MAX_BID, OFFSET, DRY))
    matches = 0
    last_est = None
    idle = 0
    while TARGET_MATCHES == 0 or matches < TARGET_MATCHES:
        if not screencap():
            time.sleep(2); continue
        bottom = ocr_bottom()

        if '进入游戏' in bottom:
            log('login screen, enter game')
            tap(*LOGIN_BTN)
            time.sleep(4)
            continue

        if ('数量耗尽' in bottom) or ('继续行动' in bottom):
            tap(*CONFIRM_BTN)
            time.sleep(1)
            continue

        if '开始行动' in bottom:
            log('setup, start match')
            if crop((90, 20, 330, 100)):
                log('coins: %s' % ocr())
            last_est = None
            idle = 0
            tap(*START_BTN)
            time.sleep(1.6)
            if screencap():
                c = ocr_center()
                if '确认' in c or '确定' in c or '数量耗尽' in c:
                    log('prompt, confirm')
                    tap(*CONFIRM_BTN)
            time.sleep(3)
            continue

        if '排位赛' in bottom or ('仓库' in bottom and '俱乐部' in bottom):
            log('lobby, enter ranked')
            tap(*RANK_BTN)
            time.sleep(4)
            continue

        if '领取补偿' in bottom:
            log('claim compensation')
            tap(450, 1487)
            time.sleep(2.5)
            continue

        if '再来一局' in bottom:
            matches += 1
            log('match done (%d)' % matches)
            if TARGET_MATCHES and matches >= TARGET_MATCHES:
                log('target reached')
                break
            tap(*NEXT_BTN)
            time.sleep(4)
            last_est = None
            continue

        if '返回大厅' in bottom:
            matches += 1
            log('match done via back (%d)' % matches)
            if TARGET_MATCHES and matches >= TARGET_MATCHES:
                break
            tap(*BACK_BTN)
            time.sleep(4)
            last_est = None
            continue

        if '跳过动画' in bottom:
            if screencap():
                crop((250, 950, 900, 1260))
                log('settlement: %s' % ocr())
            tap(*SKIP_BTN)
            time.sleep(1)
            continue

        if '点击空白' in bottom:
            tap(*DISMISS)
            time.sleep(1)
            continue

        if '已提交' in bottom:
            time.sleep(2)
            continue

        est = None
        if ('出价' in bottom or '托管' in bottom) and '工具' in bottom:
            est = ocr_est()
        if est is not None:
            if est != last_est:
                target = max(MIN_BID, int(est * AGGR) - OFFSET)
                if MAX_BID:
                    target = min(target, MAX_BID)
                log('est=%d target=%d' % (est, target))
                ok = bid_amount(target, est)
                last_est = est if ok else None
            time.sleep(1)
            continue

        idle += 1
        if idle % 4 == 0:
            c = ocr_center()
            if '资产要求' in c:
                log('room map, select room')
                tap(*ROOM_BTN)
                time.sleep(2)
            elif '仓库剩余空间不足' in c:
                log('warehouse full, recycle collectibles')
                tap(650, 960)      # 前往清理
                time.sleep(2)
                tap(750, 1325)     # 回收藏品
                time.sleep(2)
                for _ in range(6):
                    tap(750, 1357)   # 快速回收
                    time.sleep(1.2)
                    tap(650, 1290)   # 确认回收（无弹窗时无害）
                    time.sleep(1.0)
                    tap(450, 1300)   # 奖励页：点击空白处关闭
                    time.sleep(0.8)
                tap(540, 1357)     # 取消（退出回收模式）
                time.sleep(1.5)
                tap(450, 1545)     # 大厅
                time.sleep(3)
            elif '网络断开' in c or '重新连接' in c:
                log('network lost, confirm reconnect')
                tap(650, 960)
                time.sleep(3)
            elif '确定' in c or '确认' in c:
                log('dialog detected, confirm')
                tap(*CONFIRM_BTN)
            elif idle % 12 == 0:
                pos = [(790, 260), (830, 330), (640, 305), (830, 460), (860, 80)]
                log('idle, dismiss popup at %s' % (pos[(idle // 12) % len(pos)],))
                tap(*pos[(idle // 12) % len(pos)])
        time.sleep(1.5)
    log('# done')

if __name__ == '__main__':
    main()
