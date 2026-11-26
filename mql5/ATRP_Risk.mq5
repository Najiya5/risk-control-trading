//+------------------------------------------------------------------+
//|                                                   ATRP_Risk.mq5  |
//|    ATRP 波动率与阈值线 —— 放在副图窗口                             |
//|                                                                  |
//|    ATRP = ((ATR(3) + ATR(10)) / 2) / Close * 100                 |
//|    阈值 = MA(ATRP, 20) * Factor                                  |
//|                                                                  |
//|    判定：                                                         |
//|      ATRP > 阈值  → 触发风控（不开新仓 / 持仓减半）                |
//|      ATRP ≤ 阈值  → 正常                                          |
//|                                                                  |
//|    ★ Factor 硬下限 1.4，低于此值会严重耽误策略运行                 |
//+------------------------------------------------------------------+
#property copyright "risk-control system"
#property version   "1.00"
#property indicator_separate_window
#property indicator_buffers 5
#property indicator_plots   3

#property indicator_label1  "ATRP"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrAqua
#property indicator_width1  2

#property indicator_label2  "阈值 MA×Factor"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrOrange
#property indicator_width2  2

#property indicator_label3  "超阈值"
#property indicator_type3   DRAW_HISTOGRAM
#property indicator_color3  clrCrimson
#property indicator_width3  2

input group "=== ATRP 参数 ==="
input int    InpAtrPeriod1 = 3;        // ATR 短周期
input int    InpAtrPeriod2 = 10;       // ATR 长周期
input int    InpMaPeriod   = 20;       // 阈值均线周期
input double InpFactor     = 1.4;      // 阈值倍数（硬下限 1.4）

input group "=== 显示 ==="
input bool   InpAlerts     = true;     // 触发时弹窗提醒
input color  InpAlertColor = clrCrimson; // 触发标记颜色

double BufAtrp[];
double BufThr[];
double BufOver[];
double BufAtr1[];
double BufAtr10[];

int hAtr1  = INVALID_HANDLE;
int hAtr10 = INVALID_HANDLE;

bool  mWasOver = false;
ulong mLastAlertBar = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BufAtrp, INDICATOR_DATA);
   SetIndexBuffer(1, BufThr, INDICATOR_DATA);
   SetIndexBuffer(2, BufOver, INDICATOR_DATA);
   SetIndexBuffer(3, BufAtr1, INDICATOR_CALCULATIONS);
   SetIndexBuffer(4, BufAtr10, INDICATOR_CALCULATIONS);

   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, 0.0);

   IndicatorSetString(INDICATOR_SHORTNAME,
                      StringFormat("ATRP Risk (×%.1f)", InpFactor));
   IndicatorSetInteger(INDICATOR_DIGITS, 4);

   hAtr1  = iATR(_Symbol, _Period, InpAtrPeriod1);
   hAtr10 = iATR(_Symbol, _Period, InpAtrPeriod2);

   if(hAtr1 == INVALID_HANDLE || hAtr10 == INVALID_HANDLE)
   {
      Print("创建 ATR 句柄失败");
      return INIT_FAILED;
   }

   if(InpFactor < 1.4)
      Print("⚠ 警告：Factor=", DoubleToString(InpFactor, 2),
            " 低于硬下限 1.4，会严重耽误策略运行！");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hAtr1  != INVALID_HANDLE) IndicatorRelease(hAtr1);
   if(hAtr10 != INVALID_HANDLE) IndicatorRelease(hAtr10);
   ChartRedraw();
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   int need = InpMaPeriod + InpAtrPeriod2 + 5;
   if(rates_total < need)
      return 0;

   double atr1[], atr10[];
   if(CopyBuffer(hAtr1, 0, 0, rates_total, atr1) <= 0)  return 0;
   if(CopyBuffer(hAtr10, 0, 0, rates_total, atr10) <= 0) return 0;

   int start = (prev_calculated == 0) ? 0 : MathMax(prev_calculated - 2, 1);

   for(int i = start; i < rates_total; i++)
   {
      if(i == 0 || close[i] <= 0)
      {
         BufAtrp[i] = 0.0;
         continue;
      }
      BufAtrp[i] = ((atr1[i] + atr10[i]) / 2.0) / close[i] * 100.0;
   }

   for(int i = MathMax(start, InpMaPeriod); i < rates_total; i++)
   {
      double s = 0;
      int cnt = 0;
      for(int k = i - InpMaPeriod + 1; k <= i; k++)
      {
         if(BufAtrp[k] > 0) { s += BufAtrp[k]; cnt++; }
      }
      if(cnt < InpMaPeriod / 2) continue;

      double thr = (s / cnt) * InpFactor;
      BufThr[i] = thr;

      if(BufAtrp[i] > thr)
         BufOver[i] = BufAtrp[i];
      else
         BufOver[i] = 0.0;
   }

   //--- 最新一根触发提醒
   int last = rates_total - 1;
   if(InpAlerts && last >= InpMaPeriod && BufThr[last] > 0)
   {
      bool nowOver = (BufAtrp[last] > BufThr[last]);
      ulong barTime = (ulong)time[last];

      if(nowOver && !mWasOver && barTime != mLastAlertBar)
      {
         string msg = StringFormat(
            "%s %s | ATRP %.4f%% > 阈值 %.4f%% | 触发风控",
            _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period),
            BufAtrp[last], BufThr[last]);
         Print(msg);
         if(InpAlerts) Alert(msg);
         mLastAlertBar = barTime;
      }
      mWasOver = nowOver;
   }

   return rates_total;
}
//+------------------------------------------------------------------+
