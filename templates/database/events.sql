-- Event sourcing / outbox pattern schema
-- For reliable event publishing and eventual consistency

CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type VARCHAR(100) NOT NULL,  -- e.g., 'User', 'Order'
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(255) NOT NULL,      -- e.g., 'UserCreated', 'OrderPlaced'
    event_data JSONB NOT NULL,
    event_version INT DEFAULT 1,
    correlation_id UUID,
    causation_id UUID,
    published BOOLEAN DEFAULT false,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_aggregate CHECK (aggregate_type ~ '^[A-Z][a-zA-Z]+$')
);

-- Indexes for events
CREATE INDEX idx_events_aggregate ON events(aggregate_type, aggregate_id);
CREATE INDEX idx_events_event_type ON events(event_type);
CREATE INDEX idx_events_published ON events(published) WHERE published = false;
CREATE INDEX idx_events_created_at ON events(created_at);
CREATE INDEX idx_events_correlation ON events(correlation_id);

-- Outbox table for reliable message publishing
CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    topic VARCHAR(255) NOT NULL,          -- Kafka topic or routing key
    message_key VARCHAR(255),
    message_value JSONB NOT NULL,
    headers JSONB,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, published, failed
    attempts INT DEFAULT 0,
    error_message TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for outbox
CREATE INDEX idx_outbox_status ON outbox(status) WHERE status = 'pending';
CREATE INDEX idx_outbox_topic ON outbox(topic);
CREATE INDEX idx_outbox_created_at ON outbox(created_at);

-- Trigger to update outbox updated_at
CREATE TRIGGER update_outbox_updated_at BEFORE UPDATE ON outbox
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to get next sequence number for aggregate
CREATE OR REPLACE FUNCTION get_next_sequence(
    p_aggregate_type VARCHAR,
    p_aggregate_id UUID
) RETURNS BIGINT AS $$
DECLARE
    v_sequence BIGINT;
BEGIN
    SELECT COALESCE(MAX(event_version), 0) + 1
    INTO v_sequence
    FROM events
    WHERE aggregate_type = p_aggregate_type
    AND aggregate_id = p_aggregate_id;
    
    RETURN v_sequence;
END;
$$ LANGUAGE plpgsql;
