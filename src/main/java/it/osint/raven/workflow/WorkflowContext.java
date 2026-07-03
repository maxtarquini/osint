package it.osint.raven.workflow;

import it.osint.raven.dto.source.RawDocumentDto;
import it.osint.raven.dto.source.SourceDto;

import java.io.Serializable;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Shared, engine-independent state passed across all workflow nodes.
 * <p>
 * The context is intentionally independent from Spring, LangGraph4j and
 * persistence technologies. Nodes can use it to exchange typed artifacts, keep
 * execution metadata, record warnings/errors, publish audit events and collect
 * metrics without expanding the context with node-specific fields.
 */
public class WorkflowContext implements Serializable {

    private UUID workflowId;
    private String workflowName;
    private Instant startedAt;
    private volatile Instant updatedAt;
    private SourceDto source;
    private RawDocumentDto rawDocument;
    private StructuredDocument document;
    private final Map<Class<?>, WorkflowArtifact> outputs;
    private final Map<String, WorkflowArtifact> capabilityOutputs;
    private final Map<String, Object> variables;
    private final List<WorkflowEvent> events;
    private final List<String> warnings;
    private final List<WorkflowError> errors;
    private final Map<String, Object> metrics;
    private volatile WorkflowStatus status;

    /**
     * Creates a context with generated workflow id, current timestamps and CREATED status.
     */
    public WorkflowContext() {
        this(UUID.randomUUID(), null, Instant.now(), Instant.now(), null, null, null, WorkflowStatus.CREATED);
    }

    /**
     * Creates a context for the given workflow name.
     *
     * @param workflowName human-readable workflow name
     */
    public WorkflowContext(String workflowName) {
        this(UUID.randomUUID(), workflowName, Instant.now(), Instant.now(), null, null, null, WorkflowStatus.CREATED);
    }

    /**
     * Creates a context with explicit core metadata.
     *
     * @param workflowId workflow execution identifier
     * @param workflowName human-readable workflow name
     * @param startedAt workflow start timestamp
     * @param updatedAt last update timestamp
     * @param source source being processed
     * @param rawDocument acquired raw document
     * @param document structured document produced by a parser
     * @param status workflow lifecycle status
     */
    public WorkflowContext(
            UUID workflowId,
            String workflowName,
            Instant startedAt,
            Instant updatedAt,
            SourceDto source,
            RawDocumentDto rawDocument,
            StructuredDocument document,
            WorkflowStatus status
    ) {
        this.workflowId = workflowId == null ? UUID.randomUUID() : workflowId;
        this.workflowName = workflowName;
        this.startedAt = startedAt == null ? Instant.now() : startedAt;
        this.updatedAt = updatedAt == null ? this.startedAt : updatedAt;
        this.source = source;
        this.rawDocument = rawDocument;
        this.document = document;
        this.outputs = new ConcurrentHashMap<>();
        this.capabilityOutputs = new ConcurrentHashMap<>();
        this.variables = new ConcurrentHashMap<>();
        this.events = new CopyOnWriteArrayList<>();
        this.warnings = new CopyOnWriteArrayList<>();
        this.errors = new CopyOnWriteArrayList<>();
        this.metrics = new ConcurrentHashMap<>();
        this.status = status == null ? WorkflowStatus.CREATED : status;
    }

    /**
     * Stores an output using its runtime class as artifact type.
     *
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(T object) {
        return put((String) null, object);
    }

    /**
     * Stores an output using its runtime class as artifact type and preserving producer provenance.
     *
     * @param producedBy node or agent that produced the object
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(String producedBy, T object) {
        if (object == null) {
            throw new IllegalArgumentException("object must not be null");
        }
        return putArtifact(new WorkflowArtifact(null, object.getClass(), object, producedBy, Instant.now()));
    }

    /**
     * Stores an output with an explicit declared type.
     *
     * @param type declared artifact type
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(Class<? super T> type, T object) {
        return put(null, type, object);
    }

    /**
     * Stores an output with an explicit declared type and producer provenance.
     *
     * @param producedBy node or agent that produced the object
     * @param type declared artifact type
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(String producedBy, Class<? super T> type, T object) {
        if (object == null) {
            throw new IllegalArgumentException("object must not be null");
        }
        if (type == null) {
            throw new IllegalArgumentException("type must not be null");
        }
        if (!type.isInstance(object)) {
            throw new IllegalArgumentException("object is not an instance of " + type.getName());
        }
        return putArtifact(new WorkflowArtifact(null, type, object, producedBy, Instant.now()));
    }

    /**
     * Stores an output under a named workflow capability.
     *
     * @param capability declared output capability
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(WorkflowCapability capability, T object) {
        return put(null, capability, object);
    }

    /**
     * Stores an output under a named workflow capability and preserves producer provenance.
     *
     * @param producedBy node or agent that produced the object
     * @param capability declared output capability
     * @param object output object to store
     * @param <T> output type
     * @return this context
     */
    public <T> WorkflowContext put(String producedBy, WorkflowCapability capability, T object) {
        if (object == null) {
            throw new IllegalArgumentException("object must not be null");
        }
        if (capability == null) {
            throw new IllegalArgumentException("capability must not be null");
        }
        if (!capability.type().isInstance(object)) {
            throw new IllegalArgumentException("object is not an instance of " + capability.type().getName());
        }
        WorkflowArtifact artifact = new WorkflowArtifact(null, capability.type(), object, producedBy, Instant.now());
        outputs.put(capability.type(), artifact);
        capabilityOutputs.put(capability.qualifiedName(), artifact);
        capability.aliases().forEach(alias ->
                capabilityOutputs.put(
                        WorkflowCapability.qualifiedName(capability.namespace(), alias, capability.version()),
                        artifact
                )
        );
        touch();
        return this;
    }

    /**
     * Stores a pre-built workflow artifact.
     *
     * @param artifact artifact to store
     * @return this context
     */
    public WorkflowContext putArtifact(WorkflowArtifact artifact) {
        if (artifact == null) {
            throw new IllegalArgumentException("artifact must not be null");
        }
        outputs.put(artifact.type(), artifact);
        touch();
        return this;
    }

    /**
     * Reads a typed output from the context.
     *
     * @param type requested type
     * @param <T> requested type
     * @return optional typed output
     */
    public <T> Optional<T> get(Class<T> type) {
        return findArtifact(type).map(WorkflowArtifact::value).map(type::cast);
    }

    /**
     * Reads a named capability output from the context.
     *
     * @param capability requested capability
     * @param <T> requested type
     * @return optional typed output
     */
    public <T> Optional<T> get(WorkflowCapability capability) {
        return findArtifact(capability).map(artifact -> castCapabilityValue(capability, artifact.value()));
    }

    /**
     * Reads artifact metadata and value for the requested type.
     *
     * @param type requested type
     * @param <T> requested type
     * @return optional workflow artifact
     */
    public <T> Optional<WorkflowArtifact> getArtifact(Class<T> type) {
        return findArtifact(type);
    }

    /**
     * Reads artifact metadata and value for the requested named capability.
     *
     * @param capability requested capability
     * @return optional workflow artifact
     */
    public Optional<WorkflowArtifact> getArtifact(WorkflowCapability capability) {
        return findArtifact(capability);
    }

    /**
     * Checks whether the context contains an output assignable to the requested type.
     *
     * @param type requested type
     * @return true when an output exists
     */
    public boolean contains(Class<?> type) {
        return findArtifact(type).isPresent();
    }

    /**
     * Checks whether the context contains an output for the requested named capability.
     *
     * @param capability requested capability
     * @return true when a matching output exists
     */
    public boolean contains(WorkflowCapability capability) {
        return findArtifact(capability).isPresent();
    }

    /**
     * Reads a required typed output.
     *
     * @param type requested type
     * @param <T> requested type
     * @return typed output
     * @throws IllegalStateException when no output exists for the requested type
     */
    public <T> T require(Class<T> type) {
        return get(type).orElseThrow(() -> new IllegalStateException("Missing workflow output: " + type.getName()));
    }

    /**
     * Reads a required named capability output.
     *
     * @param capability requested capability
     * @param <T> requested type
     * @return typed output
     * @throws IllegalStateException when no output exists for the requested capability
     */
    public <T> T require(WorkflowCapability capability) {
        Optional<T> value = get(capability);
        if (value.isEmpty()) {
            throw new IllegalStateException("Missing workflow capability: " + capability.id());
        }
        return value.get();
    }

    /**
     * Stores a temporary variable.
     *
     * @param key variable key
     * @param value variable value
     * @return this context
     */
    public WorkflowContext variable(String key, Object value) {
        putInMap(variables, key, value, "variable key");
        event("context", WorkflowEventType.VARIABLE_SET, "Variable recorded: " + key);
        return this;
    }

    /**
     * Stores a workflow metric.
     *
     * @param key metric key
     * @param value metric value
     * @return this context
     */
    public WorkflowContext metric(String key, Object value) {
        putInMap(metrics, key, value, "metric key");
        event("context", WorkflowEventType.METRIC_RECORDED, "Metric recorded: " + key);
        return this;
    }

    /**
     * Adds a non-fatal warning.
     *
     * @param message warning message
     * @return this context
     */
    public WorkflowContext warning(String message) {
        warnings.add(message);
        event("context", WorkflowEventType.WARNING, message);
        touch();
        return this;
    }

    /**
     * Adds a workflow error.
     *
     * @param error workflow error
     * @return this context
     */
    public WorkflowContext error(WorkflowError error) {
        if (error == null) {
            throw new IllegalArgumentException("error must not be null");
        }
        errors.add(error);
        event(error.node(), WorkflowEventType.ERROR, error.message());
        touch();
        return this;
    }

    /**
     * Adds a workflow error from an exception.
     *
     * @param node node or agent where the exception occurred
     * @param throwable exception to describe
     * @return this context
     */
    public WorkflowContext error(String node, Throwable throwable) {
        return error(WorkflowError.from(node, throwable));
    }

    /**
     * Adds a workflow error from explicit values.
     *
     * @param node node or agent where the error occurred
     * @param exception exception class name or code
     * @param message error message
     * @return this context
     */
    public WorkflowContext error(String node, String exception, String message) {
        return error(new WorkflowError(node, exception, message, Instant.now()));
    }

    /**
     * Adds an audit event.
     *
     * @param node node or agent that emitted the event
     * @param type event classification
     * @param message event message
     * @return this context
     */
    public WorkflowContext event(String node, WorkflowEventType type, String message) {
        events.add(new WorkflowEvent(Instant.now(), node, type, message));
        touch();
        return this;
    }

    /**
     * Updates workflow status.
     *
     * @param status new workflow status
     * @return this context
     */
    public WorkflowContext status(WorkflowStatus status) {
        if (status == null) {
            throw new IllegalArgumentException("status must not be null");
        }
        this.status = status;
        event("context", WorkflowEventType.STATUS_CHANGED, "Workflow status changed to " + status);
        return this;
    }

    /**
     * Updates the source being processed.
     *
     * @param source source DTO
     * @return this context
     */
    public synchronized WorkflowContext source(SourceDto source) {
        this.source = source;
        touch();
        return this;
    }

    /**
     * Updates the acquired raw document.
     *
     * @param rawDocument raw document DTO
     * @return this context
     */
    public synchronized WorkflowContext rawDocument(RawDocumentDto rawDocument) {
        this.rawDocument = rawDocument;
        touch();
        return this;
    }

    /**
     * Updates the structured document.
     *
     * @param document structured document
     * @return this context
     */
    public synchronized WorkflowContext document(StructuredDocument document) {
        this.document = document;
        touch();
        return this;
    }

    /**
     * Updates the workflow name.
     *
     * @param workflowName workflow name
     * @return this context
     */
    public synchronized WorkflowContext workflowName(String workflowName) {
        this.workflowName = workflowName;
        touch();
        return this;
    }

    public UUID getWorkflowId() {
        return workflowId;
    }

    public String getWorkflowName() {
        return workflowName;
    }

    public Instant getStartedAt() {
        return startedAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public SourceDto getSource() {
        return source;
    }

    public RawDocumentDto getRawDocument() {
        return rawDocument;
    }

    public StructuredDocument getDocument() {
        return document;
    }

    public Map<Class<?>, WorkflowArtifact> getOutputs() {
        return outputs;
    }

    public Map<String, WorkflowArtifact> getCapabilityOutputs() {
        return capabilityOutputs;
    }

    public Map<String, Object> getVariables() {
        return variables;
    }

    public List<WorkflowEvent> getEvents() {
        return events;
    }

    public List<String> getWarnings() {
        return warnings;
    }

    public List<WorkflowError> getErrors() {
        return errors;
    }

    public Map<String, Object> getMetrics() {
        return metrics;
    }

    public WorkflowStatus getStatus() {
        return status;
    }

    private <T> Optional<WorkflowArtifact> findArtifact(Class<T> type) {
        if (type == null) {
            throw new IllegalArgumentException("type must not be null");
        }
        WorkflowArtifact exact = outputs.get(type);
        if (exact != null && type.isInstance(exact.value())) {
            return Optional.of(exact);
        }
        return outputs.values().stream()
                .filter(artifact -> type.isAssignableFrom(artifact.type()))
                .filter(artifact -> type.isInstance(artifact.value()))
                .findFirst();
    }

    private Optional<WorkflowArtifact> findArtifact(WorkflowCapability capability) {
        if (capability == null) {
            throw new IllegalArgumentException("capability must not be null");
        }
        WorkflowArtifact exact = capabilityOutputs.get(capability.qualifiedName());
        if (exact != null && capability.type().isInstance(exact.value())) {
            return Optional.of(exact);
        }
        for (String alias : capability.aliases()) {
            WorkflowArtifact aliased = capabilityOutputs.get(
                    WorkflowCapability.qualifiedName(capability.namespace(), alias, capability.version())
            );
            if (aliased != null && capability.type().isInstance(aliased.value())) {
                return Optional.of(aliased);
            }
        }
        return Optional.empty();
    }

    @SuppressWarnings("unchecked")
    private <T> T castCapabilityValue(WorkflowCapability capability, Object value) {
        return (T) capability.type().cast(value);
    }

    private void putInMap(Map<String, Object> map, String key, Object value, String keyDescription) {
        if (key == null || key.isBlank()) {
            throw new IllegalArgumentException(keyDescription + " must not be blank");
        }
        if (value == null) {
            map.remove(key);
        } else {
            map.put(key, value);
        }
        touch();
    }

    private void touch() {
        updatedAt = Instant.now();
    }
}
