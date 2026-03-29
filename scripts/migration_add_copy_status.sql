-- Migration: Add copy_status column to whales table
-- Task: STRAT-701

ALTER TABLE whales ADD COLUMN IF NOT EXISTS copy_status VARCHAR(10) 
    DEFAULT 'none' CHECK (copy_status IN ('none', 'paper', 'live'));

-- Set paper status for selected whales
UPDATE whales SET copy_status = 'paper' 
WHERE wallet_address IN (
    '0x32ed517a571c01b6e9adecf61ba81ca48ff2f960',
    '0xd48a81db62f742c4e42d86dfc23a7ee345366e90'
);
