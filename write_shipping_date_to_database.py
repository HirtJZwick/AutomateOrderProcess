import storage
import sqlite3  
import os
import json


def main():
    #Read all json files in the shipping_date_results folder
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shipping_date_results")
    for filename in os.listdir(results_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(results_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                shipping_date = data.get("shipping_date")
                #Get dossier_no from the filename (remove .json)
                dossier_no = os.path.splitext(filename)[0]
                #Split text by space and get first element
                dossier_no = dossier_no.split(" ")[0]
                #Remove the letters from the dossier_no
                dossier_no = ''.join(filter(str.isdigit, dossier_no))
                print(dossier_no)
                if shipping_date and dossier_no:
                    #Update the database with the shipping date
                    conn = storage.connect()
                    try:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE orders SET shipping_date = ? WHERE dossier_no = ?",
                            (shipping_date, dossier_no)
                        )
                        conn.commit()
                    finally:
                        conn.close()



if __name__ == "__main__":
    main()