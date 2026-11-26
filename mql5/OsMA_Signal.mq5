//+------------------------------------------------------------------+
//|                                                 OsMA_Signal.mq5  |
//|    OsMA 与信号线 —— 放在副图窗口                                   |
//|                                                                  |
//|    做多：OsMA > 0 且 Signal > 0（两线都在零轴以上）                |
//|    做空：OsMA < 0 且 Signal < 0（两线都在零轴以下）                |
//|    平仓：任一信号消失                                            |
//|                                                                  |
//|    背景色提示：                                                    |
//|      绿色带 = 可做多区间                                          |
//|      红色带 = 可做空区间                                          |
//+------------------------------------------------------------------+
#property copyright "risk-control system"
#property version   "1.00"
#property indicator_separate_window
#property indicator_buffers 4
#property indicator_plots   4

#property indicator_label1  "OsMA"
#property indicator_type1   DRAW_HISTOGRAM
#property indicator_color1  clrDodgerBlue
#property indicator_width1  2

#property indicator_label2  "Signal"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrOrange
#property indicator_width2  2

#property indicator_label3  "多头区间"
#property indicator_type3   DRAW_HISTOGRAM
#property indicator_color3  clrDarkGreen
#property indicator_width3  3

#property indicator_label4  "空头区间"
#property indicator_type4   DRAW_HISTOGRAM
#property indicator_color4  clrDarkRed
#property indicator_width4  3

input group "=== OsMA 参数 ==="
input int    InpFastEMA      = 5;      // 快线周期
input int    InpSlowEMA      = 20;     // 慢线周期
input int    InpSignalEMA    = 30;     // 信号线周期
input double InpWeightBody   = 0.7;    // 实体权重
input double InpWeightShadow = 0.3;    // 影线权重
input bool   InpShowZones    = true;   // 显示多空区间带

double BufOsma[];
double BufSignal[];
double BufLongZone[];
double BufShortZone[];

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BufOsma, INDICATOR_DATA);
   SetIndexBuffer(1, BufSignal, INDICATOR_DATA);
   SetIndexBuffer(2, BufLongZone, INDICATOR_DATA);
   SetIndexBuffer(3, BufShortZone, INDICATOR_DATA);

   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetDouble(3, PLOT_EMPTY_VALUE, 0.0);

   IndicatorSetString(INDICATOR_SHORTNAME, "OsMA Signal");
   IndicatorSetInteger(INDICATOR_DIGITS, 4);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectDelete(0, "OsMA_zero");
   ChartRedraw();
}

//+------------------------------------------------------------------+
double WeightedPrice(const double o, const double c,
                     const double h, const double l)
{
   double sum = InpWeightBody + InpWeightShadow;
   if(sum == 0.0) sum = 1.0;
   return (InpWeightBody * (o + c) / 2.0 + InpWeightShadow * (h + l) / 2.0) / sum;
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
   if(rates_total < InpSlowEMA + InpSignalEMA + 5)
      return 0;

   static double wp[];
   ArrayResize(wp, rates_total);
   for(int i = 0; i < rates_total; i++)
      wp[i] = WeightedPrice(open[i], close[i], high[i], low[i]);

   double aF   = 2.0 / (InpFastEMA + 1.0);
   double aS   = 2.0 / (InpSlowEMA + 1.0);
   double aSig = 2.0 / (InpSignalEMA + 1.0);

   // 全量重算（数据量不大，简单可靠）
   double emaFast = wp[0];
   double emaSlow = wp[0];
   double sig     = 0.0;

   for(int i = 0; i < rates_total; i++)
   {
      emaFast = wp[i] * aF + emaFast * (1.0 - aF);
      emaSlow = wp[i] * aS + emaSlow * (1.0 - aS);

      double osma = emaFast - emaSlow;
      BufOsma[i] = osma;

      if(i == 0) sig = osma;
      else sig = osma * aSig + sig * (1.0 - aSig);
      BufSignal[i] = sig;

      // 区间带
      if(InpShowZones)
      {
         if(osma > 0 && sig > 0)
            BufLongZone[i] = MathMax(MathAbs(osma), MathAbs(sig));
         else
            BufLongZone[i] = 0.0;

         if(osma < 0 && sig < 0)
            BufShortZone[i] = -MathMax(MathAbs(osma), MathAbs(sig));
         else
            BufShortZone[i] = 0.0;
      }
      else
      {
         BufLongZone[i] = 0.0;
         BufShortZone[i] = 0.0;
      }
   }

   return rates_total;
}
//+------------------------------------------------------------------+
