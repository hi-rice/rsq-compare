"""공유용 정적 결과 요약. 원본·전체 경로는 상세 시트에 남긴다."""
import math
import statistics
import pandas as pd
from openpyxl.chart import BarChart,Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Font,PatternFill,Alignment
from rsq_compare import APP_NAME,APP_VERSION


def statistics_for(records):
    vals=[r['q'] for r in records if r['selected'] and r['q'] is not None and not math.isnan(r['q'])]
    n=len(vals);mean=statistics.fmean(vals) if n else None;pop=statistics.pstdev(vals) if n else None
    return [n,mean,statistics.stdev(vals) if n>1 else None,pop,pop/mean if mean not in (None,0) else None]


def add_summary(wb,measurements):
    ws=wb.create_sheet('결과 요약',0);wb.active=0
    ws.append([f'{APP_NAME} v{APP_VERSION} · 결과 요약'])
    ws.append(['고정 저장본 · 입력용 아님. Excel 편집 시 통계는 재계산되지 않습니다.'])
    ws.append(['DIS 기록값의 선택 회차 비교 · 재계산/보간/품질 판정 없음 · COV는 무차원'])
    row=5
    for measurement in measurements:
        records=measurement['records'];unit=measurement.get('unit') or '단위 미확인'
        values=statistics_for(records)
        ws.cell(row,1,'지점');ws.cell(row,2,measurement.get('point') or '지점 미지정')
        ws.cell(row+1,1,'측정일시');ws.cell(row+1,2,measurement.get('time') or '시각 미확인')
        ws.cell(row+2,1,'사용 DIS');ws.cell(row+2,2,measurement.get('dis') or '없음')
        ws.cell(row+3,1,'코드/지역');ws.cell(row+3,2,f"{measurement.get('code') or '공식 코드 없음'} / {measurement.get('region') or '지역 미입력'}")
        headers=['유효 선택 수',f'산술평균 ({unit})',f'표본SD (n−1, {unit})',f'모SD (n, {unit})','COV (무차원)']
        for col,label in enumerate(headers,1):ws.cell(row+5,col,label)
        for col,value in enumerate(values,1):ws.cell(row+6,col,value)
        ws.cell(row+8,1,'모든 회차 · 미선택은 통계 제외, 요약 없음은 0이 아님')
        start=row+9
        cols=['선택 여부','회차',f'유량 ({unit})','상태/제외 사유','시작 시각(DIS 원문)','선택 회차','미선택 회차']
        for col,label in enumerate(cols,1):ws.cell(start,col,label)
        for i,r in enumerate(records,start+1):
            state='요약 없음 / 원본 빈값' if r['q'] is None else '선택' if r['selected'] else '사용자 미선택'
            data=['선택' if r['selected'] else '미선택',r['label'],r['q'],state,r.get('time'),r['q'] if r['selected'] else None,r['q'] if not r['selected'] else None]
            for col,value in enumerate(data,1):
                cell=ws.cell(i,col,value)
                if isinstance(value,str):cell.data_type='s'
        if records:
            chart=BarChart();chart.type='col';chart.grouping='stacked';chart.overlap=100
            chart.title=f"{measurement.get('point') or '지점 미지정'} · 회차 유량"
            chart.y_axis.title=f'유량 ({unit})';chart.x_axis.title='원래 T번호';chart.legend.position='b'
            chart.add_data(Reference(ws,min_col=6,max_col=7,min_row=start,max_row=start+len(records)),titles_from_data=True)
            chart.set_categories(Reference(ws,min_col=2,min_row=start+1,max_row=start+len(records)))
            chart.dispBlanksAs='gap';chart.width=20;chart.height=11
            chart.dataLabels=DataLabelList();chart.dataLabels.showVal=True;chart.dataLabels.numFmt='0.0000'
            chart.series[0].graphicalProperties.solidFill='2563A8';chart.series[1].graphicalProperties.solidFill='C3CCD6'
            ws.add_chart(chart,f'I{row}')
        for rr in (row+5,start):
            for cell in ws[rr][:7]:cell.font=Font(bold=True,color='16365C');cell.fill=PatternFill('solid',fgColor='DCEBFA')
        row=max(start+len(records)+4,row+25)
    for cells in ws:
        for cell in cells:
            cell.alignment=Alignment(vertical='center',wrap_text=True)
            if isinstance(cell.value,str):cell.data_type='s'
            if isinstance(cell.value,float):cell.number_format='0.0000'
        ws.row_dimensions[cells[0].row].height=24
    for col,width in {'A':18,'B':25,'C':24,'D':25,'E':32,'F':18,'G':18,'H':3,'I':18}.items():ws.column_dimensions[col].width=width
    ws.freeze_panes='C15';ws.sheet_view.showGridLines=False;ws.protection.sheet=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    return ws


def from_session(sd,selected,context=None):
    from rsq_compare.core.tables import q_unit
    context=context or {}
    starts=[r.dis_row_raw.get('start') for r in sd.records if r.dis_row_raw and r.dis_row_raw.get('start')]
    return {'point':context.get('river_name'),'code':context.get('site_code'),'region':context.get('sigungu'),
            'time':min(starts) if starts else None,'dis':sd.dis_path.name if sd.dis_path else None,'unit':q_unit(sd),
            'records':[dict(label=r.label,q=r.total_q,selected=r.num in selected,time=(r.dis_row_raw or {}).get('start')) for r in sd.records]}


def from_database(sess,all_tr):
    blocks=[]
    for _,s in sess.iterrows():
        records=[dict(label=r.label,q=None if pd.isna(r.total_q) else float(r.total_q),selected=bool(r.compare_selected),time=r.start_time_raw) for _,r in all_tr[all_tr.session_id==s.id].iterrows()]
        clean=lambda x:None if pd.isna(x) else x
        blocks.append(dict(point=clean(s.river_name),code=clean(s.site_code),region=clean(s.sigungu),time=clean(s.first_start_time),dis=clean(s.dis_file),unit=clean(s.q_unit),records=records))
    return blocks
