"""읽기 전용 입력 지문과 보수적인 측정 관계 판별."""
import hashlib
import json

from rsq_compare.core.discovery import DETAIL_RE


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fingerprint(sd):
    from rsq_compare.core.db import sha256_file
    files = {'dis': sd.dis_path}
    if sd.files.rsqmb:
        files['rsqmb'] = sd.files.rsqmb
    # 실제 선택되지 않은 좌표계의 상세 파일도 변경 감지에 포함한다.
    for p in sorted(sd.files.folder.iterdir(),key=lambda p:p.name):
        m = DETAIL_RE.fullmatch(p.name)
        if m and m['session'] == sd.files.name:
            base = f"T{int(m['num']):04d}.{m['ext'].lower()}"
            role,number = base,1
            while role in files:
                number += 1
                role = f'{base}#{number}'
            files[role] = p
    manifest = {role: {'sha256': sha256_file(p), 'path': str(p.resolve()), 'size': p.stat().st_size}
                for role, p in files.items()}
    hashes = {k: v['sha256'] for k,v in manifest.items()}
    detail = {k:v for k,v in hashes.items() if k not in ('dis','rsqmb')}
    # DIS에 기록된 원래 측정 파일 식별자. 이름/시각만 같은 경우는 확인 후보일 뿐이다.
    anchors = [(r.dis_row_raw.get('file'), r.dis_row_raw.get('start'))
               for r in sd.records if r.dis_row_raw and r.dis_row_raw.get('file')]
    anchors.sort(key=lambda row:tuple(str(x) for x in row))
    return dict(manifest=manifest, content=digest(hashes), detail=digest(detail) if detail and any(not df.empty for store in (sd.sum_dfs,sd.vel_dfs,sd.snr_dfs) for df in store.values()) else None,
                anchor=digest(anchors) if anchors else None)


def validate_comparison(sess):
    if sess.empty:
        return
    pending = sess[sess.get('review_status', 'confirmed') == 'pending'] if 'review_status' in sess else sess.iloc[:0]
    if not pending.empty:
        raise ValueError('측정 관계 확인 필요: ' + ', '.join(f"#{int(x)}" for x in pending.id))
    if 'measurement_id' in sess:
        groups = sess.measurement_id.fillna(sess.id)
        dup = sess[groups.duplicated(keep=False)]
        if not dup.empty:
            raise ValueError('같은 측정의 버전은 하나만 체크하세요: ' + ', '.join(f"#{int(x)}" for x in dup.id))


def copy_inputs(con, old, new):
    # 이전 행은 그대로 보존한다. 새 버전에 이미 입력한 값은 덮어쓰지 않는다.
    for col in ('memo','operator','site_code','site_code_source'):
        con.execute(f'UPDATE sessions SET {col}=COALESCE({col},(SELECT {col} FROM sessions WHERE id=?)) WHERE id=?', (old,new))
    con.execute('''INSERT OR IGNORE INTO reference_q(session_id,ref_q,unit,source,memo,updated_at)
                   SELECT ?,ref_q,unit,source,memo,updated_at FROM reference_q WHERE session_id=?''',(new,old))
    for col in ('gh_manual','gh_manual_time','gh_manual_note'):
        con.execute(f"""UPDATE transects SET {col}=COALESCE({col},(SELECT p.{col} FROM transects p
                        WHERE p.session_id=? AND p.num=transects.num)) WHERE session_id=?""",(old,new))
    con.execute("""UPDATE transects SET compare_selected=(SELECT p.compare_selected FROM transects p
                   WHERE p.session_id=? AND p.num=transects.num)
                   WHERE session_id=? AND selection_explicit=0 AND EXISTS
                   (SELECT 1 FROM transects p WHERE p.session_id=? AND p.num=transects.num)""",(old,new,old))
