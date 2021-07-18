import time
from ib_insync import *
from ib_insync.contract import Index, Option, Stock
from ib_insync.ib import IB
import pandas as pd
from ta.trend import ema_indicator

# read parameters from csv:
dataframe = pd.read_csv("Yaz_Trading_Bot_Parameters.csv")
print(dataframe)
stop_loss_percent = dataframe.loc[0][1]
profit_booking_percent = dataframe.loc[1][1]

# Logging into Interactive Broker TWS
ib = IB()
# port for IB gateway : 4002
# port for IB TWS : 7497
ib.connect('127.0.0.1', 7497, clientId=1)

# STOCK_TRADE = ["TRADED", "TRADED_LONG", "TRADED_SHORT"]
# TRADED <- 0 Means There Exists No Open Trades, 1 Means Otherwise
# TRADED_LONG <- 0 No Position, 1 Open Long Position
# TRADED_SHORT <- 0 No Position, 1 Open Short Position
order_status = [0, 0, 0]

# To get the current market value, first create a contract for the underlyer,
# we are selecting Tesla for now with SMART exchanges:
stock = Stock('TSLA', 'SMART', 'USD')
qty = 1
ib.sleep(1)

# function for rounding strike prices:
def roundStrikePrice(x, base=5):
    print( "rounded value: ", base * round(x/base))
    return base * round(x/base)

# Fetching historical data when market is closed for testing purpose and EMA values:
# For 55 EMA and 4 EMA we need previous 55 and 4 candles of 15 min each,
# so they cant be obtained during only live real time market data, we need historical data as below:
market_data = pd.DataFrame(
        ib.reqHistoricalData(
            stock,
            endDateTime='',
            durationStr='4 D',
            barSizeSetting='15 mins',
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=True
        ))

print("Market data: ", market_data)

# last candle close, 4EMA and 55EMA values:
last_close = market_data['close'].iloc[-1]
ema_value_4 = ema_indicator(market_data['close'], window=4).iloc[-1]
ema_value_55 = ema_indicator(market_data['close'], window=55).iloc[-1]

print("last close: ", last_close)
print("4EMA: ", ema_value_4)
print("55EMA: ", ema_value_55)

## STARTING THE ALGORITHM ##
# Time frame: 6.30 hrs
StartTime = pd.to_datetime("9:30").tz_localize('America/New_York')
TimeNow = pd.to_datetime(ib.reqCurrentTime()).tz_convert('America/New_York')
EndTime = pd.to_datetime("16:30").tz_localize('America/New_York')

# Waiting for Market to Open
if StartTime > TimeNow:
    wait = (StartTime - TimeNow).total_seconds()
    print("Waiting for Market to Open..")
    print(f"Sleeping for {wait} seconds")
    time.sleep(wait)
    time.sleep(3*60)

# Run the algorithm till the daily time frame exhausts:
while TimeNow <= EndTime:
    print("Trading started!")
    
    ##### CALLS ####

    # 1. LONG ENTRY CONDITION
    '''
    Long Entry Condition.
    --------------------
    i.e. If last_close > 4ema > 55ema then CALL BUY contract:
    Long Entry: the 15min Bar candle has closed ABOVE the 55EMA
    And If 4EMA > 55EMA; trade long
    '''
    print("checking for long entry condition.")
    if order_status[0] == 0 and order_status[1] == 0:
        if last_close > ema_value_4 and ema_value_4 > ema_value_55:
            print("Checking for Open Buy Positions..\n")
            order_status[0] = 1
            ib.qualifyContracts(stock)
            print("order qualified")
            # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
            ib.reqMarketDataType(1)
            # Then get the ticker
            [ticker] = ib.reqTickers(stock)
            print("ticker: ", ticker)
            CurrentStrike = ticker.marketPrice()
            ib.sleep(1)
            # The following request fetches a list of option chains:
            options_chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
            print("options_chains: ", options_chains)
            # In this case we're only interested in the weekly options trading on SMART:
            option_weekly_chains = next(c for c in options_chains if c.tradingClass == 'TSLA' and c.exchange == 'SMART')
            # taking first ITM strike in CALL options:
            strikes = [roundStrikePrice(CurrentStrike) - 5]
            # selecting next 3 week expiry:
            expirations = sorted(exp for exp in option_weekly_chains.expirations)[:3]
            print("expirations: ", expirations)
            # For CALL option
            rights = ['C']
            print("selected strikes: ", strikes)
            # From this we can build all the option contracts that meet our conditions:
            contracts = [Option('TSLA', expiration, strike, right, 'SMART', tradingClass='TSLA')
                    for right in rights
                    for expiration in expirations
                    for strike in strikes]

            option_contracts = ib.qualifyContracts(*contracts)
            print("Number of contracts for eligible strikes in CALL:", len(option_contracts))
            if (len(option_contracts)):
                print("first ITM contract from strike: ", option_contracts[0])
                option_contract = option_contracts[0]
                # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
                ib.reqMarketDataType(1)
                # Then get the ticker.
                [ticker] = ib.reqTickers(option_contract)
                print("ticker: ", ticker)
                # Take the last traded price of ticker:
                CurrentValue = ticker.close
                print("current last traded price value of the ticker: ", CurrentValue)
                dps = str(ib.reqContractDetails(option_contract)[0].minTick + 1)[::-1].find('.') - 1
                lmtPrice = round(CurrentValue - ib.reqContractDetails(option_contract)[0].minTick * 2,dps)
                print("Trading Long")
                # building order
                entry_order = ib.bracketOrder(
                    'BUY',
                    qty,
                    limitPrice= lmtPrice,
                    takeProfitPrice=CurrentValue + CurrentValue*(profit_booking_percent/100),
                    stopLossPrice=CurrentValue - CurrentValue*(stop_loss_percent/100)
                )
                for o in entry_order:
                    entry_trade = ib.placeOrder(option_contract, o)
                    print("CALL BUY order placed")
                    order_status[1] == 1

                # print trades:
                print("Trade log for CALL BUY: ", entry_trade.log)
        
        else:
            print("long entry condition not met.")

    # Check if open order and long entry exists and we meet exit condition:
    if order_status[0] == 1 and order_status[1] == 1 and ema_value_4 < ema_value_55:
        ib.cancelOrder(entry_order)
        print("Exiting the Long Trade!")
        order_status[0] == 0
        order_status[1] == 0

    ##### PUTS ####
    # 2. SHORT ENTRY CONDITION
    '''
    Short Entry Condition.
    --------------------
    # If last_close < 4ema < 55ema then PUT BUY contract
    i.e. Short Entry: the 15min Bar candle has closed below the 55EMA
    and If 4EMA < 55EMA; trade short
    '''
    print("checking for short entry condition.")
    if order_status[0] == 0 and order_status[2] == 0:
        if last_close < ema_value_4 and ema_value_4 < ema_value_55:
            print("Checking for Open Short Sell Positions..\n")
            order_status[0] == 1
            print("Trading Short")
            ib.qualifyContracts(stock)
            print("order qualified")
            # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
            ib.reqMarketDataType(1)
            # Then get the ticker. Requesting a ticker can take up to 11 seconds.
            [ticker] = ib.reqTickers(stock)
            print("ticker: ", ticker)
            # Take the current market value of the ticker:
            CurrentStrike = ticker.marketPrice()
            ib.sleep(1)
            # The following request fetches a list of option chains:
            options_chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
            print("options_chains: ", pd.DataFrame(options_chains))
            # In this case we're only interested in the weekly options trading on SMART:
            option_weekly_chains = next(c for c in options_chains if c.tradingClass == 'TSLA' and c.exchange == 'SMART')
            # taking first ITM strike in PUT options:
            strikes = [roundStrikePrice(CurrentStrike)]
            # selecting next 3 week expiry:
            expirations = sorted(exp for exp in option_weekly_chains.expirations)[:3]
            print("expirations: ", expirations)
            # For PUT option
            rights = ['P']
            print("selected strikes: ", strikes)
            # From this we can build all the option contracts that meet our conditions:
            contracts = [Option('TSLA', expiration, strike, right, 'SMART', tradingClass='TSLA')
                    for right in rights
                    for expiration in expirations
                    for strike in strikes]

            option_contracts = ib.qualifyContracts(*contracts)
            print("Number of contracts for eligible strikes:", len(option_contracts))
            if (len(option_contracts)):
                print("first ITM contract from strike: ", option_contracts[0])
                option_contract = option_contracts[0]
                # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
                ib.reqMarketDataType(1)
                # Then get the ticker.
                [ticker] = ib.reqTickers(option_contract)
                print("ticker: ", ticker)
                # Take the last traded price of ticker:
                CurrentValue = ticker.close
                print("current last traded price value of the ticker: ", CurrentValue)
                dps = str(ib.reqContractDetails(option_contract)[0].minTick + 1)[::-1].find('.') - 1
                lmtPrice = round(CurrentValue - ib.reqContractDetails(option_contract)[0].minTick * 2,dps)
                # building order
                entry_order = ib.bracketOrder(
                    'SELL',
                    qty,
                    limitPrice= lmtPrice,
                    takeProfitPrice=CurrentValue + CurrentValue*(profit_booking_percent/100),
                    stopLossPrice=CurrentValue - CurrentValue*(stop_loss_percent/100)
                )
                for o in entry_order:
                    entry_trade = ib.placeOrder(option_contract, o)
                    print("CALL BUY order placed")
                    order_status[2] == 1

                # print trades:
                print("Trade log for PUT BUY: ", entry_trade.log)
        
        else:
            print("short entry condition not met.")

    # Check if open order and long entry exists and we meet exit condition:
    if order_status[0] == 1 and order_status[2] == 1 and ema_value_4 > ema_value_55:
        ib.cancelOrder(entry_order)
        print("Exiting the Short Trade!")
        order_status[0] == 0
        order_status[2] == 0

    # Wait for 15 mins for next candle to form:
    print("No condition met for this 15 min candle so waiting 15 mins for fetching the next candle.")
    ib.sleep(900)
    TimeNow = pd.to_datetime(ib.reqCurrentTime()).tz_convert('America/New_York')

# Disconnect IB API service after market or trades over:
ib.disconnect()

# **The ability to kill the trade while the market is trading
# master square off or square off in IB
# ib.cancelOrder()

# on bash file close:
# ib.reqGlobalCancel()