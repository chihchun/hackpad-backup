This script will pull changes from hackpad, and imported them into a git repository.

# Usage
Setup backup_list.txt and api_keys.txt, and run
  python hackpad-backup.py

The script will create a git repository at data/[domain], and commit changes into padid.txt.

## Settings
Line starts with # will be ignored, can you use it as comment.

- backup_list.txt 
  Line of a domain/page to be backed up, eg. g0v/*
  But at this moment, it supports only *.
  
- api_keys.txt
  Please put your API key, one line for one domain
  [client id] [secret] [domain]

You can find your key at https://[domain].hackpad.com/ep/account/settings/
Please note, only admin can list updated pads. Non-admin can also loop all apd, but less efficient.

# Feature & limitation
- 會備份部份歷史版本 versions, 不過不會備份所有版本, 不然太大了
- 若整個 pad 被刪掉, 備份程式不會知道, 也不會備份刪掉前的版畚
- 預設以 html 格式備份, 因為這格式能保留比較多資訊
