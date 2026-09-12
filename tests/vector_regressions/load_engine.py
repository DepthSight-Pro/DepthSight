"""Isolated regression tests of unchanged source methods, without app/DB services."""
import ast, json, math, logging, typing, os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import pandas as pd
import numpy as np

ROOT=Path(os.environ.get('VECTOR_AUDIT_SOURCE', Path(__file__).resolve().parents[2]))
source=ROOT/'bot_module/fast_vector_backtester.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FastVectorBacktester' or isinstance(n,ast.FunctionDef) and 'funding' in n.name]
ns=dict(vars(typing),pd=pd,np=np,math=math,json=json,datetime=datetime,timezone=timezone,timedelta=timedelta,
        logger=logging.getLogger('audit'),config=SimpleNamespace(BACKTEST_FUNDING_RATE_8H=0,PHANTOM_TRACKING_ENABLED=False),
        normalize_condition_type=lambda v:v)
mod=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])
exec(compile(ast.fix_missing_locations(mod),str(source),'exec'),ns)
C=ns['FastVectorBacktester']

def sim(rows,signals=None,qty=1,balance=10000,sl=5,tp=10,side='LONG',fee=0,slip=0,hold=0, extra=None):
    x=C.__new__(C)
    x.main_df=pd.DataFrame(rows,columns=['open','high','low','close'],index=pd.date_range('2026-01-01',periods=len(rows),freq='min',tz='UTC'))
    assert (x.main_df.high>=x.main_df[['open','close','low']].max(axis=1)).all()
    assert (x.main_df.low<=x.main_df[['open','close','high']].min(axis=1)).all()
    x.main_df['ATR_14']=1.
    x.signals=pd.DataFrame({'enter_short' if side=='SHORT' else 'enter_long':signals if signals is not None else [True]+[False]*(len(rows)-1)},index=x.main_df.index)
    x.strategy_json={'initialization':{'params':dict(direction=side,sl_type='percent_from_price',sl_value=sl,tp_type='percent_from_price',tp_value=tp,max_hold_candles=hold)}}
    x.strategy_json['initialization']['params'].update(extra or {})
    x.slippage_pct=slip;x.commission_pct=fee
    x.initial_balance=x.current_balance=x.peak_equity=float(balance)
    x.total_pnl_usd=x.total_commission_usd=x.max_drawdown=x.max_floating_dd=0.
    x.equity_curve=[];x._is_liquidated=False;x.is_trading_allowed=True
    x.trade_start_ts=None;x.symbol='SYNTHETIC';x.strategy_name='AUDIT';x.use_oracle=False
    x.exchange_info={};x.config=ns['config']
    x.structured_report={'event_counters':{'rejections':defaultdict(int),'trades_opened':0}}
    x._determine_position_size=lambda **kw:(qty,qty*100*sl/100,None)
    x._check_risk_limits_after_trade=lambda *a:None
    x._build_decision_trace_for_index=lambda *a:[]
    x._debug_loop_count_2=100
    x._simulate_trades_vectorized_v2()
    return x

