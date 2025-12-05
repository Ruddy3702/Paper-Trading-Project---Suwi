from fyers_apiv3 import fyersModel
import pandas as pd

def get_data():
    client_id = "4TAMLS4XXJ-100"
    access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOlsiZDoxIiwiZDoyIiwieDowIiwieDoxIl0sImF0X2hhc2giOiJnQUFBQUFCcEFqOXpyQVhDNUFTZFFqNVJZYlY5anhnVUt4TFlvWFQ5c2FSTFVCOUt2eXVsTmRnWGdOQVFLZ0JncmFXSEFGRXgzN2FicTRXa0ZJSWFGSHdHd0lYWXhOQ2hlSVVzVk5wanE4V3BiVDE0WHpXWF83Zz0iLCJkaXNwbGF5X25hbWUiOiIiLCJvbXMiOiJLMSIsImhzbV9rZXkiOiIyNTFmMjI2ZDAwZTU0MjRiNjNhOTdiZDQ0Yzg1NTJjMTFhZjk1YzM0ZmQxMWVhN2ZjYzMzYmRiOSIsImlzRGRwaUVuYWJsZWQiOiJOIiwiaXNNdGZFbmFibGVkIjoiTiIsImZ5X2lkIjoiRkFGNDM2ODEiLCJhcHBUeXBlIjoxMDAsImV4cCI6MTc2MTc4NDIwMCwiaWF0IjoxNzYxNzU0OTk1LCJpc3MiOiJhcGkuZnllcnMuaW4iLCJuYmYiOjE3NjE3NTQ5OTUsInN1YiI6ImFjY2Vzc190b2tlbiJ9.jX46ud-04vC5E5_d18VFfIfZOPVzgVj5ZZ5wizIJbUQ"
    # Initialize the FyersModel instance with your client_id, access_token, and enable async mode
    fyers = fyersModel.FyersModel(client_id=client_id, token=access_token,
                                  is_async=False, log_path="../Data/fyers_logs")

    data = {
        "symbols": "NSE:GOLDSTAR-SM"
    }

    response = fyers.quotes(data=data)
    print(response["d"])


get_data()




def write_equity_data(n):
    '''Writes n rows of output (symbol,name) and (symbol) to files NSE_EQ_names.csv and NSE_EQ_only.csv'''
    data = pd.read_csv("../Data/NSE_CM.csv", header=0)
    df = pd.DataFrame(data)

    equities = df[df['symbol'].str.endswith('-EQ')]
    eq = equities[['symbol']].head(n)
    name_eq = equities[['symbol', 'name']].head(n)

    # print(eq)
    # print(name_eq)

    # symbol, name saved to file example [NSE:FACT-EQ,FACT LTD]
    name_eq.to_csv("../NSE DATA/NSE_EQ_names.csv", index=False)

    #only symbols saved to example [fileNSE:FACT-EQ]
    eq.to_csv("../NSE DATA/NSE_EQ_only.csv", index=False)
    print(eq)
    return eq




