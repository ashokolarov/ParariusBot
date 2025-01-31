# ParariusBot

ParariusBot is a Python-based automation tool designed to streamline the housing application process on Pararius, a prominent real estate platform in the Netherlands. By leveraging predefined filters, the bot automatically applies to new property listings that match your specified criteria, saving you time and effort in your housing search.

Features
Automated Applications: Automatically submits applications to new Pararius listings that meet your predefined filters.
Customizable Filters: Set your preferences to target specific property types, locations, price ranges, and other relevant criteria.
Real-Time Monitoring: Continuously monitors Pararius for new listings, ensuring timely applications.
Requirements
Python: Ensure you have Python 3.x installed on your system.
Dependencies: Install the required Python packages using the provided requirements.txt file.
Installation
Clone the Repository:
bash
Copy
Edit
git clone https://github.com/ashokolarov/ParariusBot.git
cd ParariusBot
Install Dependencies:
bash
Copy
Edit
pip install -r requirements.txt
Configuration
Set Up Filters:
Edit the config.yaml file to define your application preferences, such as location, property type, and budget.
Personal Information:
Ensure your personal details (e.g., name, email, phone number) are correctly entered in the configuration file to facilitate the application process.
Usage
Run the bot using the following command:

bash
Copy
Edit
python main.py
The bot will start monitoring Pararius for new listings that match your criteria and automatically submit applications on your behalf.
