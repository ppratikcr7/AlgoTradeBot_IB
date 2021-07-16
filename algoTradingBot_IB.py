from datetime import time
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

# To get the current market value, first create a contract for the underlyer:
stock = Stock('AAPL', 'SMART', 'USD')
qty = 1
ib.sleep(1)

# Fetching real time bars when market is open:
# market_data = ib.reqRealTimeBars(stock, 900, 'MIDPOINT', 1, [])
# print(market_data)

# Fetching historical data when market is closed for testing purpose and EMA values:
# DOUBT: For 55 EMA and 4 EMA we need previous 55 and 4 candles of 15 min each,
# so they cant be obtained during only live real time market data, we need historical data
market_data = pd.DataFrame(
        ib.reqHistoricalData(
            stock,
            endDateTime='',
            durationStr='3 D',
            barSizeSetting='15 mins',
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=True
        ))

print(market_data['close'][0])

# last candle close, 4EMA and 55EMA:
last_close = market_data['close'][0]
ema_value_4 = ema_indicator(market_data['close'], window=4).iloc[-1]
ema_value_55 = ema_indicator(market_data['close'], window=55).iloc[-1]

# Testing data
# last_close = 150
# ema_value_4 = 149
# ema_value_55 = 148

print("last close: ", last_close)
print("4EMA: ", ema_value_4)
print("55EMA: ", ema_value_55)

## STARTING THE ALGORITHM ##
# Time frame: 6.30 hrs
StartTime = pd.to_datetime("9:30").tz_localize('America/New_York')
TimeNow = pd.to_datetime(ib.reqCurrentTime()).tz_convert('America/New_York')
EndTime = pd.to_datetime("16:00").tz_localize('America/New_York')
# for testing:
# EndTime = pd.to_datetime("20:50").tz_localize('America/New_York')

# # Waiting for Market to Open
if StartTime > TimeNow:
    wait = (StartTime - TimeNow).total_seconds()
    print("Waiting for Market to Open..")
    print(f"Sleeping for {wait} seconds")
    time.sleep(wait)
    time.sleep(3*60)

# Run the algorithm till the time frame exhausts:
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
    if last_close > ema_value_4 > ema_value_55:
        print("Checking for Open Buy Positions..\n")
        ib.qualifyContracts(stock)
        print("order qualified")
        # To avoid issues with market data permissions, we'll use delayed data:
        # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
        ib.reqMarketDataType(1)
        print("reqMarketDataType")
        # Then get the ticker. Requesting a ticker can take up to 11 seconds.
        [ticker] = ib.reqTickers(stock)
        print("ticker: ", ticker)
        # Take the current market value and bid of the ticker:
        # DOUBT: do we need to take the bid column for the selected option chain as premium.
        CurrentValue = ticker.bid()
        CurrentStrike = ticker.marketPrice()
        print("current market value of the ticker: ", CurrentValue)
        ib.sleep(1)
        # The following request fetches a list of option chains:
        options_chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        # In this case we're only interested in the weekly options trading on SMART:
        option_weekly_chains = next(c for c in options_chains if c.tradingClass == 'AAPLW' and c.exchange == 'SMART')
        
        # What we have here is the full matrix of expirations x strikes. 
        # From this we can build all the option contracts that meet our conditions:
        strike_difference = option_weekly_chains.strikes[1] - option_weekly_chains.strikes[0]
        print("strike_difference: ", strike_difference)

        strikes = [strike for strike in option_weekly_chains.strikes
                if strike %  strike_difference == 0 and CurrentStrike - 20 < strike < CurrentStrike + 20]
        expirations = sorted(exp for exp in option_weekly_chains.expirations)[:3]
        # For CALL option
        rights = ['C']
        print("selected strikes: ", strikes)
        contracts = [Option('AAPL', expiration, strike, right, 'SMART', tradingClass='AAPLW')
                for right in rights
                for expiration in expirations
                for strike in strikes]

        print("contracts for eligible strikes: ", contracts)
        option_contracts = ib.qualifyContracts(*contracts)
        print("Number of contracts for eligible strikes:", len(option_contracts))
        print("first ITM contract from strike: ",option_contracts[0])
        option_contract = option_contracts[0]

        print("Trading Long")
        # building order
        entry_order = ib.bracketOrder(
            'BUY',
            qty,
            limitPrice= CurrentValue,
            takeProfitPrice=CurrentValue + CurrentValue*profit_booking_percent,
            stopLossPrice=CurrentValue - CurrentValue*stop_loss_percent
        )
        for o in entry_order:
            entry_trade = ib.placeOrder(option_contract, o)

        # print trades:
        print(entry_trade.log)
    
    else:
        print("long entry condition not met.")

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
    if  last_close < ema_value_4 < ema_value_55:
        print("Checking for Open Short Sell Positions..\n")
        print("Trading Short")
        ib.qualifyContracts(stock)
        print("order qualified")
        # To avoid issues with market data permissions, we'll use delayed data:
        # Switch to live (1) frozen (2) delayed (3) delayed frozen (4).
        ib.reqMarketDataType(1)
        print("reqMarketDataType")
        # Then get the ticker. Requesting a ticker can take up to 11 seconds.
        [ticker] = ib.reqTickers(stock)
        print("ticker: ", ticker)
        # Take the current market value and bid of the ticker:
        CurrentValue = ticker.bid()
        CurrentStrike = ticker.marketPrice()
        print("current market value of the ticker: ", CurrentValue)
        ib.sleep(1)
        # The following request fetches a list of option chains:
        options_chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
        # In this case we're only interested in the weekly options trading on SMART:
        option_weekly_chains = next(c for c in options_chains if c.tradingClass == 'AAPLW' and c.exchange == 'SMART')
        
        # What we have here is the full matrix of expirations x strikes. 
        # From this we can build all the option contracts that meet our conditions:
        strike_difference = option_weekly_chains.strikes[1] - option_weekly_chains.strikes[0]
        print("strike_difference: ", strike_difference)

        strikes = [strike for strike in option_weekly_chains.strikes
                if strike %  strike_difference == 0 and CurrentStrike - 20 < strike < CurrentStrike + 20]
        expirations = sorted(exp for exp in option_weekly_chains.expirations)[:3]
        # For PUT option
        rights = ['P']
        print("selected strikes: ", strikes)
        contracts = [Option('AAPL', expiration, strike, right, 'SMART', tradingClass='AAPLW')
                for right in rights
                for expiration in expirations
                for strike in strikes]

        print("contracts for eligible strikes: ", contracts)
        option_contracts = ib.qualifyContracts(*contracts)
        print("Number of contracts for eligible strikes:", len(option_contracts))
        print("first ITM contract from strike: ",option_contracts[0])
        option_contract = option_contracts[0]
        # building order
        entry_order = ib.bracketOrder(
            'SELL',
            qty,
            limitPrice= CurrentValue,
            takeProfitPrice= CurrentValue + CurrentValue*profit_booking_percent,
            stopLossPrice= CurrentValue - CurrentValue*stop_loss_percent
        )
        for o in entry_order:
            entry_trade = ib.placeOrder(option_contract, o)
        # print trades:
        print(entry_trade.log)
    
    else:
        print("short entry condition not met.")

    # Wait for 15 mins for next candle to form:
    print("No condition met for this 15 min candle so waiting 15 mins for fetching the next candle.")
    ib.sleep(900)
    TimeNow = pd.to_datetime(ib.reqCurrentTime()).tz_convert('America/New_York')

# Disconnect IB API service after market or trades over:
ib.disconnect()

# **The ability to kill the trade while the market is trading
# master square off or square off in IB
# ib.cancelOrder()