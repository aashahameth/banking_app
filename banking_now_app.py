import datetime
import json # Still needed for transactions list within accounts.txt
import os
import hashlib
import getpass
import re # For basic validation (e.g., DOB)

# --- Configuration ---
USERS_FILE = "users.txt"
ACCOUNTS_FILE = "accounts.txt"
NEXT_ACC_NUM_FILE = "next_account_number.txt"
DATA_DELIMITER = "|~|" # Delimiter for fields in a line
LIST_DELIMITER = ";"   # Delimiter for items in a list (e.g., owned_accounts)

INTEREST_RATE = 0.015 # Annual interest rate (1.5%)
MIN_INITIAL_DEPOSIT = 0.0 # Minimum deposit for new accounts

# --- Global Data Stores ---
# users: Stores user login and personal information
#   Key: nic (str), Value: dict { 'name': str, 'address': str, 'dob': str,
#                                 'password_hash': str, 'role': 'admin'|'customer',
#                                 'owned_accounts': list[str] (for customers) }
users = {}

# accounts: Stores bank account details
#   Key: account_number (str), Value: dict { 'owner_nic': str, 'balance': float,
#                                            'transactions': list[dict], 'created_at': str }
accounts = {}

# Keeps track of the next account number to assign.
# Loaded from file, defaults to 1001.
next_account_number = 1001

# --- Utility Functions ---

def generate_account_number():
    """Generates a new, unique bank account number."""
    global next_account_number
    # Ensure the generated number isn't already in use
    while str(next_account_number) in accounts:
        next_account_number += 1
    acc_num = str(next_account_number)
    next_account_number += 1 # Increment for the next call
    return acc_num

def hash_password(password):
    """Hashes a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash, provided_password):
    """Verifies a provided password against a stored hash."""
    return stored_hash == hash_password(provided_password)

def get_timestamp():
    """Returns the current time as a formatted string."""
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def format_currency(amount):
    """Formats a number as currency (e.g., $1,234.50)."""
    return f"${amount:,.2f}"

def is_valid_dob(date_str):
    """Checks if a date string is in YYYY-MM-DD format using regex."""
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))

def record_transaction(acc_num, trans_type, amount, **details):
    """Adds a transaction record to an account's history."""
    if acc_num not in accounts:
        print(f"Error: Attempted to record transaction for non-existent account {acc_num}.")
        return

    transaction = {
        "timestamp": get_timestamp(),
        "type": trans_type,
        "amount": amount,
        **details
    }
    accounts[acc_num].setdefault("transactions", []).append(transaction)

# --- Data Persistence ---

def _serialize_user(nic, user_data):
    """Converts user data dictionary to a delimited string for TXT file."""
    # Ensure owned_accounts is a list and handle missing key gracefully
    owned_accounts_list = user_data.get("owned_accounts", []) if user_data.get("role") == "customer" else []
    owned_accounts_str = LIST_DELIMITER.join(owned_accounts_list)
    
    return DATA_DELIMITER.join([
        str(nic),
        str(user_data.get("name", "")),
        str(user_data.get("address", "")),
        str(user_data.get("dob", "")),
        str(user_data.get("password_hash", "")),
        str(user_data.get("role", "")),
        owned_accounts_str # This will be empty string if owned_accounts_list is empty
    ])

def _deserialize_user(line):
    """Converts a delimited string from TXT file back to user data (nic, dict)."""
    parts = line.strip().split(DATA_DELIMITER)
    if len(parts) != 7: # Expecting exactly 7 parts
        # print(f"Debug: Malformed user line (expected 7 parts, got {len(parts)}): {line.strip()}")
        return None, None
    
    nic = parts[0]
    role = parts[5]
    owned_accounts_part = parts[6]

    user_data = {
        "name": parts[1],
        "address": parts[2],
        "dob": parts[3],
        "password_hash": parts[4],
        "role": role
    }
    if role == 'customer':
        # Handles empty string for owned_accounts_part correctly (results in empty list)
        user_data["owned_accounts"] = [acc for acc in owned_accounts_part.split(LIST_DELIMITER) if acc]
    elif role == 'admin':
        # Admins don't have owned_accounts; if data exists, it's unexpected but ignored.
        if owned_accounts_part:
            # print(f"Warning: Admin user {nic} has unexpected data in owned_accounts field: '{owned_accounts_part}'. Ignoring.")
            pass 
    else: # Invalid role
        # print(f"Warning: Invalid role '{role}' for user {nic} in line: {line.strip()}")
        return None, None

    return nic, user_data


def _serialize_account(acc_num, acc_data):
    """Converts account data dictionary to a delimited string for TXT file."""
    # Transactions list is complex, so serialize it as a JSON string within the line
    transactions_json_str = json.dumps(acc_data.get("transactions", []))
    return DATA_DELIMITER.join([
        str(acc_num),
        str(acc_data.get("owner_nic", "")),
        str(float(acc_data.get("balance", 0.0))), # Ensure balance is float then string
        str(acc_data.get("created_at", "")),
        transactions_json_str
    ])

def _deserialize_account(line):
    """Converts a delimited string from TXT file back to account data (acc_num, dict)."""
    parts = line.strip().split(DATA_DELIMITER)
    if len(parts) != 5: # Expecting exactly 5 parts
        # print(f"Debug: Malformed account line (expected 5 parts, got {len(parts)}): {line.strip()}")
        return None, None
    
    acc_num = parts[0]
    balance_str = parts[2]
    transactions_json_str = parts[4]

    try:
        balance = float(balance_str)
    except ValueError:
        # print(f"Warning: Invalid balance format for account {acc_num}: '{balance_str}'. Defaulting to 0.0.")
        balance = 0.0 

    try:
        transactions_list = json.loads(transactions_json_str)
        if not isinstance(transactions_list, list): # Ensure it's a list
            # print(f"Warning: Transactions data for account {acc_num} is not a list. Defaulting to empty. Data: {transactions_json_str[:50]}")
            transactions_list = []
    except json.JSONDecodeError:
        # print(f"Warning: Could not parse transactions JSON for account {acc_num}. Defaulting to empty list. Data: {transactions_json_str[:50]}")
        transactions_list = []

    acc_data = {
        "owner_nic": parts[1],
        "balance": balance,
        "created_at": parts[3],
        "transactions": transactions_list
    }
    return acc_num, acc_data

def save_data():
    """Saves users, accounts, and next_account_number to their respective TXT files."""
    global users, accounts, next_account_number

    # Save Users
    try:
        with open(USERS_FILE, 'w') as f:
            for nic, user_data in users.items():
                f.write(_serialize_user(nic, user_data) + "\n")
    except IOError as e:
        print(f"\nError: Could not save user data to {USERS_FILE}! Changes might be lost. Details: {e}")
    except Exception as e:
        print(f"\nError: An unexpected error occurred while saving user data: {e}")

    # Save Accounts
    try:
        with open(ACCOUNTS_FILE, 'w') as f:
            for acc_num, acc_data in accounts.items():
                f.write(_serialize_account(acc_num, acc_data) + "\n")
    except IOError as e:
        print(f"\nError: Could not save account data to {ACCOUNTS_FILE}! Changes might be lost. Details: {e}")
    except Exception as e:
        print(f"\nError: An unexpected error occurred while saving account data: {e}")

    # Save Next Account Number
    try:
        with open(NEXT_ACC_NUM_FILE, 'w') as f:
            f.write(str(next_account_number))
    except IOError as e:
        print(f"\nError: Could not save next account number to {NEXT_ACC_NUM_FILE}! Details: {e}")
    except Exception as e:
        print(f"\nError: An unexpected error occurred while saving next account number: {e}")

def load_data():
    """Loads data from TXT files. Initializes first admin if no data/users exist."""
    global users, accounts, next_account_number
    users = {} 
    accounts = {}
    next_account_number = 1001 

    any_file_issue = False # Tracks if any file is missing or has issues

    # Load Users
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line_content = line.strip()
                    if not line_content: continue # Skip empty lines
                    nic, user_data = _deserialize_user(line_content)
                    if nic and user_data:
                        users[nic] = user_data
                    else:
                        print(f"Warning: Skipping malformed user data on line {line_num} in {USERS_FILE}.")
            print(f"Loaded {len(users)} users from {USERS_FILE}.")
        except IOError as e:
            print(f"Warning: Could not read users file {USERS_FILE}. Error: {e}.")
            any_file_issue = True 
        except Exception as e: # Catch-all for other unexpected parsing issues
            print(f"Warning: An unexpected error occurred loading users from {USERS_FILE}: {e}.")
            any_file_issue = True 
    else:
        print(f"User data file ({USERS_FILE}) not found.")
        any_file_issue = True

    # Load Accounts
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line_content = line.strip()
                    if not line_content: continue
                    acc_num, acc_data = _deserialize_account(line_content)
                    if acc_num and acc_data:
                        accounts[acc_num] = acc_data
                    else:
                         print(f"Warning: Skipping malformed account data on line {line_num} in {ACCOUNTS_FILE}.")
            print(f"Loaded {len(accounts)} accounts from {ACCOUNTS_FILE}.")
        except IOError as e:
            print(f"Warning: Could not read accounts file {ACCOUNTS_FILE}. Error: {e}.")
            any_file_issue = True
        except Exception as e:
            print(f"Warning: An unexpected error occurred loading accounts from {ACCOUNTS_FILE}: {e}.")
            any_file_issue = True
    else:
        print(f"Account data file ({ACCOUNTS_FILE}) not found.")
        if not any_file_issue : any_file_issue = True # Mark issue if users file existed but this one doesn't

    # Load Next Account Number
    if os.path.exists(NEXT_ACC_NUM_FILE):
        try:
            with open(NEXT_ACC_NUM_FILE, 'r') as f:
                content = f.read().strip()
                if content.isdigit():
                    next_account_number = int(content)
                    print(f"Loaded next account number: {next_account_number} from {NEXT_ACC_NUM_FILE}.")
                else:
                    print(f"Warning: Invalid content in {NEXT_ACC_NUM_FILE} ('{content}'). Using default {next_account_number}.")
                    if not any_file_issue : any_file_issue = True 
        except IOError as e:
            print(f"Warning: Could not read {NEXT_ACC_NUM_FILE}. Error: {e}. Using default {next_account_number}.")
            if not any_file_issue : any_file_issue = True
        except Exception as e:
            print(f"Warning: An unexpected error occurred loading {NEXT_ACC_NUM_FILE}: {e}. Using default {next_account_number}.")
            if not any_file_issue : any_file_issue = True
    else:
        print(f"Next account number file ({NEXT_ACC_NUM_FILE}) not found. Using default {next_account_number}.")
        if not any_file_issue : any_file_issue = True
    
    # Post-load checks and initialization logic
    if not users : # If no users were loaded (files missing, empty, all corrupt, or first run)
        if any_file_issue : # Typically indicates first run or major data loss
            print(f"Welcome! Some data files were missing or unreadable. This may be the first run or data is incomplete.")
        else: # All files might have existed, but users.txt was empty or all lines were corrupt.
            print(f"Data files found, but no valid user data loaded.")
        _initialize_fresh_start_with_admin()
    else:
        # Perform basic data integrity checks if users were loaded
        for user_data_val in users.values(): # No need for nic here
            if user_data_val.get('role') == 'customer':
                user_data_val.setdefault('owned_accounts', []) 
        for acc_data_val in accounts.values():
             acc_data_val.setdefault("transactions", [])
        
        # Check if at least one admin exists
        has_admin = any(u.get('role') == 'admin' for u in users.values())
        if not has_admin:
            print("CRITICAL WARNING: Loaded user data, but NO admin user found!")
            print("The system may not function correctly. An admin is required for some operations.")
            print("Consider registering an admin or resetting data if issues persist.")
            # Depending on policy, could force admin creation or exit.
            # For now, allows app to continue with this warning.
        print("Data loading process complete.")


def _initialize_fresh_start_with_admin():
    """Helper to reset data and create the first admin if loading fails badly or for a fresh start."""
    global users, accounts, next_account_number
    print("\nInitializing fresh start: Resetting data stores.")
    users = {}
    accounts = {}
    next_account_number = 1001
    print("Attempting to set up a new Admin account for the fresh start...")
    if not create_first_admin(): # create_first_admin internally calls register_user
        print("Critical: Admin setup failed during fresh start. The application cannot continue without an admin. Exiting.")
        exit()
    # create_first_admin modified global `users`. Now save everything.
    save_data() # This will create the .txt files with the new admin and empty accounts/next_num.
    print("Initial Admin user created and all data files initialized/updated for fresh start.")


# --- User Management & Authentication ---

def create_first_admin():
    """Guides the creation of the very first admin user. Called during setup."""
    print("\n--- Initial Admin User Setup ---")
    print("The system requires an administrator to be set up.")
    return register_user(role='admin') 

def register_user(role='customer'):
    """Handles registration for a new user (admin or customer)."""
    print(f"\n--- Register New {role.capitalize()} ---")
    while True:
        nic = input(f"Enter {role}'s NIC (National ID, for login): ").strip()
        if not nic:
            print("NIC cannot be empty. Please try again.")
            continue
        if nic in users:
            print(f"Error: A user with NIC '{nic}' already exists. Registration failed.")
            return False 
        if DATA_DELIMITER in nic or LIST_DELIMITER in nic:
            print(f"Error: NIC cannot contain reserved characters ('{DATA_DELIMITER}', '{LIST_DELIMITER}'). Please try again.")
            continue
        break 

    name = input(f"Enter {role}'s full name: ").strip()
    #---Q 2------
    name = name.title()
    #--------------
    if DATA_DELIMITER in name or LIST_DELIMITER in name:
        print(f"Warning: Name contains reserved characters ('{DATA_DELIMITER}', '{LIST_DELIMITER}'). Please avoid them for data integrity.")
    if not name:
        print("Warning: Name has been left blank.")

    address = input(f"Enter {role}'s address: ").strip()
    if DATA_DELIMITER in address or LIST_DELIMITER in address:
         print(f"Warning: Address contains reserved characters ('{DATA_DELIMITER}', '{LIST_DELIMITER}'). Please avoid them for data integrity.")
    if not address:
        print("Warning: Address has been left blank.")

    dob = ""
    while True:
        dob_input = input(f"Enter {role}'s Date of Birth (YYYY-MM-DD): ").strip()
        if is_valid_dob(dob_input):
            dob = dob_input
            break
        else:
            print("Invalid date format. Please use YYYY-MM-DD (e.g., 1990-05-15).")

    password = ""
    while True:
        pwd1 = getpass.getpass(f"Set a password for {nic}: ")
        if not pwd1:
            print("Password cannot be empty. Please try again.")
            continue
    #--Q 3-----
        if len(pwd1) < 6:
            print("Password must be at least 6 characters.")
            continue
    #-----------
        pwd2 = getpass.getpass("Confirm password: ")
        if pwd1 == pwd2:
            password = pwd1
            break
        else:
            print("Passwords do not match. Please try again.")

    password_hash = hash_password(password)
    user_data = {
        "name": name,
        "address": address,
        "dob": dob,
        "password_hash": password_hash,
        "role": role
    }
    if role == 'customer':
        user_data["owned_accounts"] = [] 

    users[nic] = user_data
    print("-" * 30)
    print(f"{role.capitalize()} user '{nic}' ({name}) registered successfully!")
    print("-" * 30)
    return True 

def login_user():
    """Handles user login."""
    print("\n--- User Login ---")
    nic = input("Enter your NIC: ").strip()
    if nic not in users:
        print(f"Error: User with NIC '{nic}' not found.")
        return None

    user_data = users[nic]

    for attempt in range(3, 0, -1): 
        password = getpass.getpass(f"Enter password for {nic}: ")
        if verify_password(user_data["password_hash"], password):
            print(f"\nLogin successful. Welcome, {user_data['name']} ({user_data['role'].capitalize()})!")
            return nic, user_data 
        else:
            print(f"Incorrect password. {attempt - 1} attempts remaining.")

    print("Authentication failed after 3 attempts. Please try logging in again.")
    return None

# --- Customer Banking Operations ---

def create_customer_bank_account(customer_nic):
    """Creates a new bank account for the given customer NIC."""
    print("\n--- Create New Bank Account ---")
    customer_data = users.get(customer_nic)
    if not customer_data or customer_data['role'] != 'customer':
        print("Error: Invalid customer profile for account creation. This shouldn't happen.")
        return

    initial_deposit = 0.0
    while True:
        try:
            amount_str = input(f"Enter initial deposit amount (min {format_currency(MIN_INITIAL_DEPOSIT)}): ").strip()
            if not amount_str and MIN_INITIAL_DEPOSIT == 0.0: 
                initial_deposit = 0.0
                break
            initial_deposit = float(amount_str)
            if initial_deposit < MIN_INITIAL_DEPOSIT:
                print(f"Initial deposit must be at least {format_currency(MIN_INITIAL_DEPOSIT)}.")
            else:
                break 
        except ValueError:
            print("Invalid amount. Please enter a number (e.g., 50.00).")

    acc_num = generate_account_number()
    accounts[acc_num] = {
        "owner_nic": customer_nic,
        "balance": initial_deposit,
        "transactions": [], 
        "created_at": get_timestamp()
    }

    if initial_deposit > 0:
        record_transaction(acc_num, "Initial Deposit", initial_deposit)

    customer_data.setdefault("owned_accounts", []).append(acc_num) 

    print("-" * 30)
    print("Bank account created successfully!")
    print(f"  Account Holder NIC: {customer_nic}")
    print(f"  New Account Number: {acc_num}")
    print(f"  Current Balance: {format_currency(initial_deposit)}")
    print("-" * 30)
    save_data()

def choose_customer_account(customer_nic, action_verb="perform an action on"):
    """Lets a customer choose one of their accounts."""
    customer_data = users.get(customer_nic) 
    owned_accounts = customer_data.get("owned_accounts", [])

    if not owned_accounts:
        print("You don't have any bank accounts yet. Please create one first.")
        return None

    if len(owned_accounts) == 1:
        print(f"Automatically selected your only account: {owned_accounts[0]}")
        return owned_accounts[0]

    print(f"\nSelect account to {action_verb}:")
    for i, acc_num in enumerate(owned_accounts):
        balance = accounts.get(acc_num, {}).get('balance', 0.0) 
        print(f"  {i + 1}. Account {acc_num} (Balance: {format_currency(balance)})")

    while True:
        try:
            choice_str = input("Enter choice number: ").strip()
            choice = int(choice_str)
            if 1 <= choice <= len(owned_accounts):
                return owned_accounts[choice - 1]
            else:
                print(f"Invalid choice. Please enter a number between 1 and {len(owned_accounts)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")

def make_deposit(customer_nic):
    """Handles depositing funds into a customer's chosen account."""
    print("\n--- Deposit Funds ---")
    acc_num = choose_customer_account(customer_nic, "deposit into")
    if not acc_num:
        return 

    account = accounts.get(acc_num) 
    if not account:
         print(f"Internal Error: Account {acc_num} data not found. Please contact support.")
         return

    while True:
        try:
            amount_str = input("Enter amount to deposit: ").strip()
            amount = float(amount_str)
            if amount > 0:
                break
            else:
                print("Deposit amount must be positive.")
        except ValueError:
            print("Invalid amount. Please enter a number (e.g., 100.50).")

    account["balance"] += amount
    record_transaction(acc_num, "Deposit", amount)

    print(f"\nSuccessfully deposited {format_currency(amount)}.")
    print(f"New balance for account {acc_num}: {format_currency(account['balance'])}")
    save_data()

def make_withdrawal(customer_nic):
    """Handles withdrawing funds from a customer's chosen account."""
    print("\n--- Withdraw Funds ---")
    acc_num = choose_customer_account(customer_nic, "withdraw from")
    if not acc_num:
        return

    account = accounts.get(acc_num)
    if not account:
         print(f"Internal Error: Account {acc_num} data not found. Please contact support.")
         return

    if account["balance"] == 0:
        print(f"Account {acc_num} has no funds to withdraw.")
        return

    while True:
        try:
            amount_str = input(f"Enter amount to withdraw (Available: {format_currency(account['balance'])}): ").strip()
            amount = float(amount_str)
            if amount > 0:
                break
            else:
                print("Withdrawal amount must be positive.")
        except ValueError:
            print("Invalid amount. Please enter a number (e.g., 50.00).")

    if amount > account["balance"]:
        print("\nError: Insufficient funds for this withdrawal.")
        print(f"  Available balance: {format_currency(account['balance'])}")
        print(f"  Requested amount: {format_currency(amount)}")
    else:
        account["balance"] -= amount
        record_transaction(acc_num, "Withdrawal", amount)
        print(f"\nSuccessfully withdrew {format_currency(amount)}.")
        print(f"Remaining balance for account {acc_num}: {format_currency(account['balance'])}")
        save_data()

def display_balance(customer_nic):
    """Displays the balance for a customer's chosen account."""
    print("\n--- Check Account Balance ---")
    acc_num = choose_customer_account(customer_nic, "check balance for")
    if not acc_num:
        return

    account = accounts.get(acc_num)
    if not account:
         print(f"Internal Error: Account {acc_num} data not found. Please contact support.")
         return

    print("-" * 30)
    print(f"Account Holder NIC: {account['owner_nic']}")
    print(f"Account Number: {acc_num}")
    print(f"Current Balance: {format_currency(account['balance'])}")
    print("-" * 30)

def display_transaction_history(customer_nic):
    """Displays transaction history for a customer's chosen account."""
    print("\n--- Account Transaction History ---")
    acc_num = choose_customer_account(customer_nic, "view history for")
    if not acc_num:
        return

    account = accounts.get(acc_num)
    if not account:
         print(f"Internal Error: Account {acc_num} data not found. Please contact support.")
         return

    print("-" * 75) 
    print(f"Transaction History for Account: {acc_num} (Owner NIC: {account['owner_nic']})")
    print("-" * 75)

    transactions = account.get("transactions", [])
    if not transactions:
        print("No transactions found for this account.")
    else:
        print(f"{'Timestamp':<20} | {'Type':<18} | {'Amount':<15} | Details")
        print("-" * 75)
        for tx in transactions:
            details_parts = [] 
            if tx["type"] == "Transfer Sent":
                 details_parts.append(f"To Acct: {tx.get('to_account', 'N/A')}")
            elif tx["type"] == "Transfer Received":
                 details_parts.append(f"From Acct: {tx.get('from_account', 'N/A')}")
            elif tx["type"] == "Interest Applied":
                 details_parts.append(f"Rate: {tx.get('rate', INTEREST_RATE)*100:.2f}% p.a.")
            details_str = ", ".join(details_parts) if details_parts else "N/A"
            print(f"{tx['timestamp']:<20} | {tx['type']:<18} | {format_currency(tx['amount']):<15} | {details_str}")
    print("-" * 75)

def transfer_funds(customer_nic):
    """Allows a customer to transfer funds from one of their accounts to another account."""
    print("\n--- Transfer Funds ---")
    print("First, select YOUR account to transfer FROM:")
    source_acc_num = choose_customer_account(customer_nic, "transfer from")
    if not source_acc_num:
        return

    source_account = accounts.get(source_acc_num)
    if not source_account: 
         print(f"Internal Error: Source account {source_acc_num} not found. Please contact support.")
         return

    dest_acc_num = input("Enter the RECIPIENT'S account number: ").strip()
    if not dest_acc_num:
        print("Recipient account number cannot be empty.")
        return
    if source_acc_num == dest_acc_num:
        print("Error: Cannot transfer funds to the same account.")
        return

    dest_account = accounts.get(dest_acc_num)
    if not dest_account:
        print(f"Error: Recipient account '{dest_acc_num}' does not exist.")
        return

    while True:
        try:
            amount_str = input(f"Enter amount to transfer (from {source_acc_num}): ").strip()
            amount = float(amount_str)
            if amount > 0:
                break
            else:
                print("Transfer amount must be positive.")
        except ValueError:
            print("Invalid amount. Please enter a number (e.g., 25.00).")

    if amount > source_account["balance"]:
        print("\nError: Insufficient funds in your account to complete this transfer.")
        print(f"  Available in {source_acc_num}: {format_currency(source_account['balance'])}")
        print(f"  Requested for transfer: {format_currency(amount)}")
        return

    source_account["balance"] -= amount
    dest_account["balance"] += amount

    record_transaction(source_acc_num, "Transfer Sent", amount, to_account=dest_acc_num)
    record_transaction(dest_acc_num, "Transfer Received", amount, from_account=source_acc_num)

    print("\nTransfer successful!")
    print(f"  {format_currency(amount)} transferred from account {source_acc_num} to account {dest_acc_num}.")
    print(f"  Your new balance (Acc {source_acc_num}): {format_currency(source_account['balance'])}")
    save_data()

# --- Admin Operations ---

def view_all_users():
    """Admin: Displays a list of all registered users."""
    print("\n--- List All Registered Users ---")
    if not users:
        print("No users are currently registered in the system.")
        return

    print("-" * 70) 
    print(f"{'NIC':<15} | {'Name':<20} | {'Role':<10} | {'Owned Accounts'}")
    print("-" * 70)
    for nic, data in users.items():
        owned_acc_str = ", ".join(data.get('owned_accounts', [])) if data['role'] == 'customer' else 'N/A'
        if not owned_acc_str and data['role'] == 'customer': owned_acc_str = "None"
        print(f"{nic:<15} | {data.get('name', 'N/A'):<20} | {data.get('role', 'N/A').capitalize():<10} | {owned_acc_str}")
    print("-" * 70)

def view_all_bank_accounts():
    """Admin: Displays a list of all bank accounts in the system."""
    print("\n--- List All Bank Accounts ---")
    if not accounts:
        print("No bank accounts currently exist in the system.")
        return

    print("-" * 75) 
    print(f"{'Account No.':<12} | {'Owner NIC':<15} | {'Owner Name':<20} | {'Balance':<15} | {'Created At'}")
    print("-" * 75)
    for acc_num, data in accounts.items():
        owner_nic = data.get('owner_nic', 'UNKNOWN')
        owner_name = users.get(owner_nic, {}).get('name', 'N/A') if owner_nic != 'UNKNOWN' else 'N/A'
        balance_str = format_currency(data.get('balance', 0.0))
        created_at_str = data.get('created_at', 'N/A')
        print(f"{acc_num:<12} | {owner_nic:<15} | {owner_name:<20} | {balance_str:<15} | {created_at_str}")
    print("-" * 75)


def apply_interest_to_all_accounts():
    """Admin: Calculates and applies annual interest to all eligible accounts."""
    print("\n--- Apply Annual Interest to All Accounts ---")
    if not accounts:
        print("No accounts in the system to apply interest to.")
        return

    applied_count = 0
    total_interest_applied = 0.0
    print(f"Applying annual interest at {INTEREST_RATE*100:.2f}%...")

    for acc_num, account_data in accounts.items():
        current_balance = account_data.get("balance", 0.0)
        if current_balance > 0: 
            interest_earned = round(current_balance * INTEREST_RATE, 2) 
            if interest_earned > 0: 
                account_data["balance"] += interest_earned
                record_transaction(acc_num, "Interest Applied", interest_earned, rate=INTEREST_RATE)
                applied_count += 1
                total_interest_applied += interest_earned

    if applied_count > 0:
        print(f"\nInterest successfully applied to {applied_count} account(s).")
        print(f"Total interest distributed: {format_currency(total_interest_applied)}")
        save_data()
    else:
        print("\nNo interest was applied (e.g., no accounts had positive balances or interest was negligible).")


# --- Menus and Main Application Flow ---

def show_login_menu():
    """Displays the main login/registration menu."""
    print("\n===== Welcome to Simple Bank App =====")
    print("1. Login")
    print("2. Register New Customer")
    print("3. Exit Application")
    print("====================================")

def show_customer_menu(customer_name):
    """Displays the menu for a logged-in customer."""
    print(f"\n===== Customer Dashboard ({customer_name}) =====")
    print("1. Create New Bank Account")
    print("2. Deposit Funds")
    print("3. Withdraw Funds")
    print("4. Check Account Balance")
    print("5. View Transaction History")
    print("6. Transfer Funds")
    print("7. Logout")
    print("==========================================")

def show_admin_menu(admin_name):
    def display_customer_list(all_users_data):
    customer_info_parts = []
    for nic, user_data in all_users_data.items():
        if user_data.get('role') == 'customer':
            customer_name = user_data.get('name', 'N/A')
            customer_info_parts.append(f"{nic}: {customer_name}")

    print("\n--- Customer List ---")
    if not customer_info_parts:
        print("No customers exist.")
    else:
        print(", ".join(customer_info_parts) + ".")
    
    """Displays the menu for a logged-in admin."""
    print(f"\n===== Admin Panel ({admin_name}) =====")
    print("1. View All Users")
    print("2. View All Bank Accounts")
    print("3. Apply Annual Interest to All Accounts")
    print("4. Logout")
    print("==================================")

def run_customer_session(customer_nic, customer_data):
    """Handles the interactive session for a logged-in customer."""
    customer_name = customer_data['name']
    while True:
        show_customer_menu(customer_name)
        choice = input("Enter your choice (1-7): ").strip()

        if choice == '1':
            create_customer_bank_account(customer_nic)
        elif choice == '2':
            make_deposit(customer_nic)
        elif choice == '3':
            make_withdrawal(customer_nic)
        elif choice == '4':
            display_balance(customer_nic)
        elif choice == '5':
            display_transaction_history(customer_nic)
        elif choice == '6':
            transfer_funds(customer_nic)
        elif choice == '7':
            print(f"\nLogging out, {customer_name}. Have a great day!")
            break 
        else:
            print("Invalid choice. Please select an option from the menu.")

        input("\nPress Enter to return to the customer menu...")
        # os.system('cls' if os.name == 'nt' else 'clear')

 def run_admin_session(admin_nic, admin_data):
    """Handles the interactive session for a logged-in admin."""
    admin_name = admin_data['name']
    while True:
        show_admin_menu(admin_name)
        choice = input("Enter your choice (1-5): ").strip() # Updated choice range

        if choice == '1':
            view_all_users()
        elif choice == '2':
            view_all_bank_accounts()
        elif choice == '3':
            apply_interest_to_all_accounts()
        elif choice == '4':  # New One <---
            display_customer_list(users) 
        elif choice == '5':  # Logout option (was 4)
            print(f"\nLogging out, Admin {admin_name}.")
            break
        else:
            print("Invalid choice. Please select an option from the menu (1-5).") # Updated error message

        input("\nPress Enter to return to the admin menu...")
        # os.system('cls' if os.name == 'nt' else 'clear') # Optional: clear screen


def run_app():
    """Main function to run the banking application."""
    load_data() 

    while True:
        show_login_menu()
        choice = input("Choose an option (1-3): ").strip()

        if choice == '1': 
            login_result = login_user()
            if login_result:
                nic, user_data = login_result 
                if user_data['role'] == 'admin':
                    run_admin_session(nic, user_data)
                elif user_data['role'] == 'customer':
                    run_customer_session(nic, user_data)
                else:
                    print(f"Error: Unknown user role '{user_data['role']}' for user {nic}.")
            else:
                input("\nPress Enter to return to the main menu...")

        elif choice == '2': 
            if register_user(role='customer'):
                 save_data() 
                 print("Registration successful. You can now log in.")
            input("\nPress Enter to return to the main menu...")

        elif choice == '3': 
            print("\nExiting the Banking Application...")
            save_data() 
            print("Goodbye!")
            break 
        else:
            print("Invalid choice. Please enter a number between 1 and 3.")
            input("\nPress Enter to continue...")
        # os.system('cls' if os.name == 'nt' else 'clear')

# --- Application Start ---
if __name__ == "__main__":
    run_app()
