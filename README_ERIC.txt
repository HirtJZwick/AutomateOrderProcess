===============================================================================
 ZwickRoell Order Tracker
===============================================================================

A dashboard that reads the order folders on SharePoint/OneDrive, pulls the key
data out of each order's Checklist and Order Confirmation, asks two Power
Automate flows for the contacts and the shipping date, and shows everything in
one searchable list in your browser.


-------------------------------------------------------------------------------
 1. INSTALL  (do this once)
-------------------------------------------------------------------------------

Double-click:

    install.bat

It sets up everything on its own:
  * finds Python on your PC, or downloads and installs Python 3.12 if you
    don't have it (no administrator rights needed)
  * creates a private virtual environment inside this folder, so nothing
    else on your PC is touched
  * installs the packages listed in requirements.txt
  * checks that they all load correctly

This takes 1-3 minutes. When you see "Setup complete!" you can close the
window.


-------------------------------------------------------------------------------
 2. START  (do this whenever you want to use it)
-------------------------------------------------------------------------------

Double-click:

    start.bat

A black server window opens and your browser opens automatically at

    http://localhost:8000

LEAVE THE BLACK WINDOW OPEN while you use the app - that window IS the
program. To shut the app down, close the black window.


-------------------------------------------------------------------------------
 3. FIRST-TIME SETUP INSIDE THE APP
-------------------------------------------------------------------------------

The app ships with the order data already loaded. The stored folder paths are
relative to the shared library, so they work on your PC too - you only have to
tell the app where that library lives on your machine:

  a) Make sure the shared order folder is synchronized to your PC with
     OneDrive, so it appears under something like

         C:\Users\<you>\OneDrive - ZwickRoell GmbH & Co. KG\...

  b) In the app, open "Settings" and set "Scan folder" to that folder - the
     one that CONTAINS the "Order_Folders" and "New_Machines_Order_Folder"
     subfolders. Do not pick one of those subfolders itself.

     That is it - the existing orders and their Refresh buttons work straight
     away.

  c) Optional: click "Scan new orders" once to pull in any order that was
     added after this package was prepared.

     The very first scan can take 15-20 MINUTES, because OneDrive has to
     download every order folder on demand. It is much faster afterwards.


-------------------------------------------------------------------------------
 4. DAILY USE
-------------------------------------------------------------------------------

  Scan new orders  Looks through both order subfolders and adds any order
                   that isn't in the list yet. Existing orders are left alone.

  Refresh          On a single order: re-reads that order's folder and asks
                   the Power Automate flows for its contacts and shipping
                   date again. Use it when documents were added to a folder.

  Search box       Filters the list by customer name as you type.

  Filter buttons   Narrow the list down by status / category.

Anything you type into a field by hand is kept. Automatic updates only ever
fill in fields that are still empty - they never overwrite your own entries.


-------------------------------------------------------------------------------
 5. GOOD TO KNOW
-------------------------------------------------------------------------------

* Shipping dates take a moment.
  The Power Automate flow writes its answer into a shared Excel workbook on
  SharePoint, and OneDrive then has to sync that workbook back down to your
  PC. That round trip takes roughly 30-60 seconds. The app waits up to 90
  seconds for it. If your connection is slower and you see
  "No shipping date found", just press Refresh again - or raise
  "flow_result_timeout_seconds" in config.json.

* An "i" next to Shipping date
  means the flow could not find a date, and hovering over it explains why.

* Close Excel.
  If you have OC_Contacts.xlsx or Dossier_Shipping_Date.xlsx open in Excel,
  Windows locks the file and the app cannot read the flow results. The app
  will tell you when this happens - just close Excel and press Refresh.

* Your data lives in eric_orders.db in this folder.
  Copy that one file if you ever want a backup or want to move the app to
  another PC.

* Nothing leaves your PC except the calls to the Power Automate flows.
  All the PDF and Word reading happens locally.


-------------------------------------------------------------------------------
 6. IF SOMETHING GOES WRONG
-------------------------------------------------------------------------------

"Setup has not been run yet"
    You started start.bat before install.bat. Run install.bat first.

The browser shows "can't reach this page"
    Give the black server window a few more seconds, then reload
    http://localhost:8000. If the black window closed immediately, run
    install.bat again - the environment is probably incomplete.

"Port 8000 already in use"
    The app is already running in another window, or something else is using
    port 8000. Close the other black window and try again.

"has no valid source_folder on disk"
    The order folders moved or aren't synced. Check the scan folder in
    Settings, then run "Scan new orders" once to re-point everything.

Nothing is being found when scanning
    Check the scan folder in Settings points at the PARENT folder that holds
    "Order_Folders" and "New_Machines_Order_Folder", and that OneDrive has
    finished syncing.
