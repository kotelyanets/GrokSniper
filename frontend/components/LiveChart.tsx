"use client";

import { memo } from "react";
import { AdvancedRealTimeChart } from "react-ts-tradingview-widgets";

const LiveChart = memo(function LiveChart() {
    return (
        <div className="w-full h-full">
            <AdvancedRealTimeChart
                symbol="BINANCE:BTCUSDT"
                theme="dark"
                width="100%"
                height="100%"
                hide_top_toolbar={false}
                hide_side_toolbar={true}
                allow_symbol_change={true}
                save_image={false}
                container_id="groksniper_chart"
                style="1"
                locale="en"
                timezone="Etc/UTC"
                backgroundColor="rgba(3, 7, 18, 0)"
            />
        </div>
    );
});

export default LiveChart;
