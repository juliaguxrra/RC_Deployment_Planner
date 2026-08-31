IF DB_ID(N'cruise_learning') IS NULL
    CREATE DATABASE cruise_learning;
GO
 
USE cruise_learning;
GO
 
DROP TABLE IF EXISTS dbo.sample_schedule;
DROP TABLE IF EXISTS dbo.route_stops;
DROP TABLE IF EXISTS dbo.route_templates;
DROP TABLE IF EXISTS dbo.ship_port_evidence;
DROP TABLE IF EXISTS dbo.ports;
DROP TABLE IF EXISTS dbo.ships;
DROP TABLE IF EXISTS dbo.seasonality;
DROP TABLE IF EXISTS dbo.sources;
GO
 
CREATE TABLE dbo.sources (
    source_id varchar(20) PRIMARY KEY,
    source_title nvarchar(220) NOT NULL,
    publisher nvarchar(100) NOT NULL,
    source_url nvarchar(1000) NOT NULL,
    fact_type varchar(20) NOT NULL CHECK (fact_type IN ('VERIFIED', 'MODELED')),
    accessed_date date NOT NULL
);
 
CREATE TABLE dbo.ships (
    ship_id varchar(20) PRIMARY KEY,
    ship_name nvarchar(100) NOT NULL,
    ship_class nvarchar(50) NOT NULL,
    service_year smallint NOT NULL,
    gross_tonnage int NOT NULL,
    double_occupancy_guests int NOT NULL,
    crew int NOT NULL,
    passenger_decks tinyint NOT NULL,
    draft_m decimal(4,2) NOT NULL,
    draft_status varchar(20) NOT NULL CHECK (draft_status IN ('VERIFIED', 'MODELED')),
    miami_scope_flag bit NOT NULL DEFAULT 1,
    model_size_experience_score decimal(3,2) NOT NULL DEFAULT 4.00,
    source_id varchar(20) NOT NULL REFERENCES dbo.sources(source_id)
);
 
CREATE TABLE dbo.ports (
    port_id varchar(20) PRIMARY KEY,
    port_name nvarchar(150) NOT NULL,
    country nvarchar(80) NOT NULL,
    latitude decimal(9,6) NOT NULL,
    longitude decimal(9,6) NOT NULL,
    homeport_flag bit NOT NULL DEFAULT 0,
    private_destination_flag bit NOT NULL DEFAULT 0,
    model_daily_ship_limit tinyint NOT NULL,
    model_daily_guest_limit int NOT NULL,
    max_draft_m decimal(4,2) NOT NULL,
    draft_status varchar(20) NOT NULL CHECK (draft_status IN ('VERIFIED', 'MODELED')),
    model_port_cost_index decimal(5,2) NOT NULL,
    model_guest_rating decimal(3,2) NOT NULL,
    model_experience_score decimal(5,2) NOT NULL,
    model_port_fee_usd decimal(6,2) NOT NULL DEFAULT 0,
    model_avg_guest_spend_usd decimal(6,2) NOT NULL DEFAULT 0,
    source_id varchar(20) NOT NULL REFERENCES dbo.sources(source_id)
);
 
CREATE TABLE dbo.seasonality (
    month_number tinyint PRIMARY KEY CHECK (month_number BETWEEN 1 AND 12),
    month_label varchar(12) NOT NULL,
    season_label varchar(30) NOT NULL,
    spend_multiplier decimal(4,2) NOT NULL,
    source_id varchar(20) NOT NULL REFERENCES dbo.sources(source_id)
);
 
CREATE TABLE dbo.ship_port_evidence (
    ship_id varchar(20) NOT NULL REFERENCES dbo.ships(ship_id),
    port_id varchar(20) NOT NULL REFERENCES dbo.ports(port_id),
    evidence_status varchar(20) NOT NULL CHECK (evidence_status IN ('VERIFIED', 'SAMPLE')),
    evidence_note nvarchar(300) NOT NULL,
    source_id varchar(20) NOT NULL REFERENCES dbo.sources(source_id),
    PRIMARY KEY (ship_id, port_id)
);
 
CREATE TABLE dbo.route_templates (
    route_id varchar(20) PRIMARY KEY,
    route_name nvarchar(180) NOT NULL,
    ship_id varchar(20) NOT NULL REFERENCES dbo.ships(ship_id),
    cruise_type varchar(30) NOT NULL CHECK (cruise_type IN ('WEEKEND', '4-5 NIGHT', '7 NIGHT', '9 NIGHT', '12 NIGHT')),
    nights tinyint NOT NULL CHECK (nights IN (3, 4, 5, 7, 9, 12)),
    region nvarchar(50) NOT NULL,
    evidence_status varchar(20) NOT NULL CHECK (evidence_status IN ('VERIFIED', 'SAMPLE')),
    source_id varchar(20) NOT NULL REFERENCES dbo.sources(source_id)
);
 
CREATE TABLE dbo.route_stops (
    route_id varchar(20) NOT NULL REFERENCES dbo.route_templates(route_id),
    day_number tinyint NOT NULL,
    port_id varchar(20) NULL REFERENCES dbo.ports(port_id),
    arrival_time time NULL,
    departure_time time NULL,
    PRIMARY KEY (route_id, day_number)
);
 
CREATE TABLE dbo.sample_schedule (
    schedule_id int IDENTITY PRIMARY KEY,
    ship_id varchar(20) NOT NULL REFERENCES dbo.ships(ship_id),
    port_id varchar(20) NOT NULL REFERENCES dbo.ports(port_id),
    call_date date NOT NULL,
    schedule_status varchar(20) NOT NULL DEFAULT 'MODELED'
);
GO