//+------------------------------------------------------------------+
//|                                                    OsMA_Risk.mq5  |
//|                    OsMA 信号 + ATRP 波动率风控 —— 可视化指标       |
//|                                                                  |
//|  拖到图表上即可看到：                                              |
//|    1. 主图：做多 / 做空 信号箭头                                  |
//|    2. 副图1：OsMA 与信号线（判断两个信号是否同号）                 |
//|    3. 副图2：ATRP 与阈值线（判断是否触发风控）                     |
//|                                                                  |
//|  信号逻辑（与 Python 回测完全一致）：                              |
//|    做多：OsMA > 0 且 Signal > 0                                  |
//|    做空：OsMA < 0 且 Signal < 0                                  |
//|    平仓：任一信号消失                                            |
//|                                                                  |
//|  ATRP 逻辑（来自 ATRP.mq4）：                                     |
//|    ATRP = ((ATR(3) + ATR(10)) / 2) / Close * 100                 |
//|    阈值 = MA(ATRP, 20) * Factor                                  |
//|    ATRP > 阈值 → 触发风控                                        |
//+------------------------------------------------------------------+
#property copyright "risk-control system"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   3

//--- 主图信号箭头
#property indicator_label1  "做多信号"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrLime
#property indicator_width1  2

#property indicator_label2  "做空信号"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrRed
#property indicator_width2  2

//--- 副图 OsMA（放在单独窗口）
#property indicator_label3  "OsMA 指标"
#property indicator_type3   DRAW_NONE
#property indicator_color3  clrNONE

//--- 输入参数
input group "=== OsMA 参数 ==="
input int    InpFastEMA    = 5;        // 快线周期
input int    InpSlowEMA    = 20;       // 慢线周期
input int    InpSignalEMA  = 30;       // 信号线周期
input double InpWeightBody = 0.7;      // 实体权重
input double InpWeightShadow = 0.3;    // 影线权重

input group "=== ATRP 参数 ==="
input int    InpAtrPeriod1 = 3;        // ATR 短周期
input int    InpAtrPeriod2 = 10;       // ATR 长周期
input int    InpMaPeriod   = 20;       // 阈值均线周期
input double InpFactor     = 1.4;      // 阈值倍数（硬下限 1.4）
input bool   InpShowArrows = true;     // 显示信号箭头
input bool   InpShowBlocked = true;    // 显示被拦截的信号（灰色）

//--- 缓冲区
double BufLong[];
double BufShort[];
double BufOsma[];
double BufSignal[];
double BufAtrp[];
double BufThr[];

//--- 全局句柄
int hAtr1 = INVALID_HANDLE;
int hAtr10 = INVALID_HANDLE;
int hMaAtrp = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   // 主图箭头
   SetIndexBuffer(0, BufLong, INDICATOR_DATA);
   PlotIndexSetInteger(0, PLOT_ARROW, 233);   // 上箭头
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetInteger(0, PLOT_DRAW_BEGIN, InpSlowEMA + InpSignalEMA);

   SetIndexBuffer(1, BufShort, INDICATOR_DATA);
   PlotIndexSetInteger(1, PLOT_ARROW, 234);   // 下箭头
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetInteger(1, PLOT_DRAW_BEGIN, InpSlowEMA + InpSignalEMA);

   SetIndexBuffer(2, BufOsma, INDICATOR_CALCULATIONS);
   SetIndexBuffer(3, BufSignal, INDICATOR_CALCULATIONS);
   SetIndexBuffer(4, BufAtrp, INDICATOR_CALCULATIONS);
   SetIndexBuffer(5, BufThr, INDICATOR_CALCULATIONS);

   // ATR 句柄
   hAtr1  = iATR(_Symbol, _Period, InpAtrPeriod1);
   hAtr10 = iATR(_Symbol, _Period, InpAtrPeriod2);
   if(hAtr1 == INVALID_HANDLE || hAtr10 == INVALID_HANDLE)
   {
      Print("创建 ATR 句柄失败");
      return INIT_FAILED;
   }

   // 检查 factor 下限
   if(InpFactor < 1.4)
      Print("警告：InpFactor=", InpFactor, " 低于 1.4，会严重耽误策略运行");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(hAtr1  != INVALID_HANDLE) IndicatorRelease(hAtr1);
   if(hAtr10 != INVALID_HANDLE) IndicatorRelease(hAtr10);
   if(hMaAtrp != INVALID_HANDLE) IndicatorRelease(hMaAtrp);
   ChartRedraw();
}

//+------------------------------------------------------------------+
//| 加权价格：实体和影线的加权平均                                    |
//+------------------------------------------------------------------+
double WeightedPrice(const double o, const double c,
                     const double h, const double l)
{
   double wb = InpWeightBody;
   double ws = InpWeightShadow;
   double sum = wb + ws;
   if(sum == 0.0) sum = 1.0;
   return (wb * (o + c) / 2.0 + ws * (h + l) / 2.0) / sum;
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
   int start = MathMax(prev_calculated, 1);
   int need = InpSlowEMA + InpSignalEMA + InpMaPeriod + InpAtrPeriod2 + 5;

   if(rates_total < need)
      return 0;

   //--- 复制 ATR
   double atr1[], atr10[];
   if(CopyBuffer(hAtr1, 0, 0, rates_total, atr1) <= 0) return 0;
   if(CopyBuffer(hAtr10, 0, 0, rates_total, atr10) <= 0) return 0;

   //--- 加权价格序列
   static double wp[];
   ArrayResize(wp, rates_total);
   for(int i = MathMax(start - 1, 0); i < rates_total; i++)
      wp[i] = WeightedPrice(open[i], close[i], high[i], low[i]);

   //--- EMA 初始化：用前 N 个的 SMA 做种子（与 MT4 一致）
   static bool inited = false;
   if(!inited || prev_calculated == 0)
   {
      ArrayInitialize(BufOsma, 0.0);
      ArrayInitialize(BufSignal, 0.0);
      ArrayInitialize(BufLong, EMPTY_VALUE);
      ArrayInitialize(BufShort, EMPTY_VALUE);
      ArrayInitialize(BufAtrp, 0.0);
      ArrayInitialize(BufThr, 0.0);

      // 快慢 EMA 种子
      if(rates_total > InpSlowEMA + 5)
      {
         double s = 0;
         for(int k = 0; k < InpFastEMA; k++) s += wp[k];
         double emaFast = s / InpFastEMA;

         s = 0;
         for(int k = 0; k < InpSlowEMA; k++) s += wp[k];
         double emaSlow = s / InpSlowEMA;

         double aF = 2.0 / (InpFastEMA + 1.0);
         double aS = 2.0 / (InpSlowEMA + 1.0);

         // 从 max(fast,slow) 开始递推（简化处理：从 0 开始全算）
         // 这里重新从 0 开始计算两个 EMA
         emaFast = wp[0];
         emaSlow = wp[0];
         for(int k = 1; k < rates_total; k++)
         {
            emaFast = wp[k] * aF + emaFast * (1.0 - aF);
            emaSlow = wp[k] * aS + emaSlow * (1.0 - aS);
            BufOsma[k] = emaFast - emaSlow;
         }

         // 信号线：OsMA 的 EMA
         double aSig = 2.0 / (InpSignalEMA + 1.0);
         double sig = BufOsma[0];
         for(int k = 1; k < rates_total; k++)
         {
            sig = BufOsma[k] * aSig + sig * (1.0 - aSig);
            BufSignal[k] = sig;
         }
      }
      inited = true;
      start = MathMax(need, 1);
   }

   //--- 计算 ATRP 和阈值
   for(int i = start; i < rates_total; i++)
   {
      if(close[i] <= 0) continue;
      double atrp = ((atr1[i] + atr10[i]) / 2.0) / close[i] * 100.0;
      BufAtrp[i] = atrp;

      // 阈值：ATRP 的 MA(20)
      if(i >= InpMaPeriod)
      {
         double s = 0;
         int cnt = 0;
         for(int k = i - InpMaPeriod + 1; k <= i; k++)
         {
            if(BufAtrp[k] > 0) { s += BufAtrp[k]; cnt++; }
         }
         if(cnt > 0) BufThr[i] = (s / cnt) * InpFactor;
      }
   }

   //--- 生成信号箭头
   if(InpShowArrows)
   {
      int s0 = MathMax(start, need);
      for(int i = s0; i < rates_total; i++)
      {
         bool wasLong  = (BufOsma[i-1] > 0 && BufSignal[i-1] > 0);
         bool wasShort = (BufOsma[i-1] < 0 && BufSignal[i-1] < 0);
         bool isLong   = (BufOsma[i]   > 0 && BufSignal[i]   > 0);
         bool isShort  = (BufOsma[i]   < 0 && BufSignal[i]   < 0);

         bool blocked = (BufAtrp[i] > BufThr[i] && BufThr[i] > 0);

         if(isLong && !wasLong)
            BufLong[i] = blocked ? EMPTY_VALUE : low[i] - 3 * _Point;

         if(isShort && !wasShort)
            BufShort[i] = blocked ? EMPTY_VALUE : high[i] + 3 * _Point;
      }
   }

   return rates_total;
}
//+------------------------------------------------------------------+
