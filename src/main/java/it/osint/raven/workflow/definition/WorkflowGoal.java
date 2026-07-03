package it.osint.raven.workflow.definition;

import it.osint.raven.workflow.WorkflowCapability;

import java.io.Serializable;
import java.lang.module.ModuleDescriptor.Version;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Immutable workflow objective declared by a {@link WorkflowDefinition}.
 * <p>
 * A goal states that the workflow should obtain a capability such as
 * {@code metadata}, {@code entities}, {@code claims}, {@code assessment} or
 * {@code neo4j}. It does not name the node that will produce the capability.
 * The future compiler will resolve goals against registered nodes.
 *
 * @param capability desired workflow capability
 * @param required true when the goal is mandatory for a successful workflow
 * @param priority priority used by future compilers when ordering objectives
 */
public record WorkflowGoal(
        WorkflowCapability capability,
        boolean required,
        int priority
) implements Serializable {

    /**
     * Creates a goal and validates non-null capability.
     */
    public WorkflowGoal {
        capability = Objects.requireNonNull(capability, "capability must not be null");
    }

    /**
     * Creates a required goal with default priority.
     *
     * @param id capability id
     * @return required workflow goal
     */
    public static WorkflowGoal required(String id) {
        return new WorkflowGoal(defaultCapability(id), true, 100);
    }

    /**
     * Creates a goal from a capability.
     *
     * @param capability desired capability
     * @param required true when mandatory
     * @param priority compiler priority
     * @return workflow goal
     */
    public static WorkflowGoal of(WorkflowCapability capability, boolean required, int priority) {
        return new WorkflowGoal(capability, required, priority);
    }

    /**
     * Validates this goal.
     *
     * @return this goal when valid
     */
    public WorkflowGoal validate() {
        if (capability == null) {
            throw new IllegalArgumentException("workflow goal capability must not be null");
        }
        if (priority < 0) {
            throw new IllegalArgumentException("workflow goal priority must not be negative");
        }
        return this;
    }

    static WorkflowGoal fromYamlValue(Object value, int defaultPriority) {
        if (value instanceof String id) {
            return new WorkflowGoal(defaultCapability(id), true, defaultPriority);
        }
        if (value instanceof Map<?, ?> map) {
            String id = stringValue(map.get("id"));
            String namespace = stringValue(map.get("namespace"));
            String description = stringValue(map.get("description"));
            Version version = parseVersion(map.get("version"));
            boolean required = booleanValue(map.get("required"), true);
            int priority = intValue(map.get("priority"), defaultPriority);
            WorkflowCapability capability = WorkflowCapability.builder()
                    .namespace(namespace == null ? WorkflowCapability.DEFAULT_NAMESPACE : namespace)
                    .id(id)
                    .description(description)
                    .type(Object.class)
                    .version(version)
                    .required(false)
                    .build();
            return new WorkflowGoal(capability, required, priority);
        }
        throw new IllegalArgumentException("workflow goal must be a string or map");
    }

    Object toYamlValue(int compactPriority) {
        if (required
                && priority == compactPriority
                && capability.namespace().equals(WorkflowCapability.DEFAULT_NAMESPACE)
                && capability.version().equals(WorkflowCapability.DEFAULT_VERSION)
                && capability.description().isBlank()
                && capability.aliases().isEmpty()
                && capability.type().equals(Object.class)) {
            return capability.id();
        }
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("id", capability.id());
        value.put("namespace", capability.namespace());
        if (!capability.description().isBlank()) {
            value.put("description", capability.description());
        }
        value.put("version", capability.version().toString());
        value.put("required", required);
        value.put("priority", priority);
        return value;
    }

    private static WorkflowCapability defaultCapability(String id) {
        return WorkflowCapability.builder()
                .id(id)
                .type(Object.class)
                .required(false)
                .build();
    }

    private static Version parseVersion(Object value) {
        if (value == null) {
            return WorkflowCapability.DEFAULT_VERSION;
        }
        try {
            return Version.parse(String.valueOf(value));
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("invalid workflow goal version: " + value, ex);
        }
    }

    private static String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static boolean booleanValue(Object value, boolean defaultValue) {
        return value == null ? defaultValue : Boolean.parseBoolean(String.valueOf(value));
    }

    private static int intValue(Object value, int defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("invalid workflow goal priority: " + value, ex);
        }
    }
}
